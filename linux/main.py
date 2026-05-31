#!/usr/bin/env python3
"""DARKMAP-Q UNO Q board entrypoint (App Lab main script).

This is the App Lab Python main on the UNO Q. It starts the full mapping
pipeline (``pipeline.py --source bridge``), edge YOLO detection, and the Flask
dashboard on the board. The laptop opens ``http://<board-ip>:8000`` in a browser
-- no TCP telemetry relay or frame forwarding required.

For laptop/dev and simulation, run the pipeline directly instead:

    python3 pipeline.py --source sim          # live map window
    python3 pipeline.py --source wallsim       # wall-follow simulator
    python3 pipeline.py --source net           # legacy laptop TCP receiver

Environment overrides::

    DARKMAP_CAMERA=0
    DARKMAP_DASHBOARD_HOST=0.0.0.0
    DARKMAP_DASHBOARD_PORT=8000
    DARKMAP_MODEL=models/yolov8n_int8.onnx
"""

from __future__ import annotations

import os
import sys
import threading
import time

_LINUX_DIR = os.path.dirname(os.path.abspath(__file__))
if _LINUX_DIR not in sys.path:
    sys.path.insert(0, _LINUX_DIR)
os.chdir(_LINUX_DIR)

try:
    from arduino.app_utils import App
except ImportError as exc:  # pragma: no cover - only on UNO Q
    raise SystemExit(
        "main.py is the UNO Q App Lab entrypoint and must run on the board.\n"
        "On the laptop use: python3 pipeline.py --source sim (or net for legacy relay)."
    ) from exc

import dashboard  # noqa: E402
import pipeline as darkmap_pipeline  # noqa: E402
from serial_bridge import BridgeSource  # noqa: E402

CAMERA_INDEX = int(os.environ.get("DARKMAP_CAMERA", "0"))
DASHBOARD_HOST = os.environ.get("DARKMAP_DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("DARKMAP_DASHBOARD_PORT", "8000"))
MODEL_PATH = os.environ.get("DARKMAP_MODEL", "models/yolov8n_int8.onnx")


def _log(msg: str) -> None:
    print(f"[uno_q] {msg}", flush=True)


def _start_dashboard() -> None:
    app = dashboard.create_app()
    _log(f"dashboard http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, threaded=True)


def _start_pipeline() -> None:
    argv = [
        "--source", "bridge",
        "--no-plot",
        "--model", MODEL_PATH,
        "--camera", str(CAMERA_INDEX),
    ]
    _log(f"pipeline argv: {' '.join(argv)}")
    code = darkmap_pipeline.main(argv)
    _log(f"pipeline exited with code {code}")


def idle_loop() -> None:
    """Keep App Lab alive; Bridge callbacks run on the main thread."""
    time.sleep(1.0)


def main() -> None:
    if not os.path.isfile(MODEL_PATH):
        _log(f"warning: model not found at {MODEL_PATH!r} — run quantize.py on dev, "
             "then copy models/yolov8n_int8.onnx to the board")

    # Register Bridge.provide on the main thread before App.run / worker threads.
    BridgeSource()

    threading.Thread(target=_start_dashboard, name="dashboard", daemon=True).start()
    threading.Thread(target=_start_pipeline, name="pipeline", daemon=True).start()
    _log("threads started; App.run() on main thread for Bridge dispatch")
    App.run(user_loop=idle_loop)


if __name__ == "__main__":
    main()
