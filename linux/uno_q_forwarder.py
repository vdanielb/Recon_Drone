#!/usr/bin/env python3
"""UNO Q board-side telemetry relay for DARKMAP-Q (legacy fallback).

**Primary deployment:** use ``main.py`` (the App Lab entrypoint) instead — it
runs mapping, edge YOLO, and the dashboard on the board; the laptop is only a
browser client.

This forwarder remains for the old laptop-hosted topology: MCU → Bridge → TCP →
laptop ``pipeline.py --source net``.

Runs on the Arduino UNO Q Linux side inside Arduino App Lab (paired with the MCU
sketch).  The sketch pushes CSV lines via ``Bridge.notify("telemetry", ...)``;
this script receives them and forwards each line over TCP to the laptop.

Join the laptop's Wi-Fi hotspot first (see ``join_hotspot.sh``).  The default
target is the Windows Mobile Hotspot gateway (``192.168.137.1``).  Override only
if your laptop uses a different subnet:

    export DARKMAP_LAPTOP_HOST=192.168.137.1  # default; Windows hotspot gateway
    export DARKMAP_LAPTOP_PORT=9009           # must match --listen-port

Do **not** run this on the laptop — use ``pipeline.py --source net`` there instead.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Optional

try:
    from arduino.app_utils import App, Bridge
except ImportError as exc:  # pragma: no cover - only available on UNO Q
    raise SystemExit(
        "uno_q_forwarder.py must run on the UNO Q via Arduino App Lab.\n"
        "On the laptop use: python3 pipeline.py --source net"
    ) from exc

# Windows Mobile Hotspot always uses 192.168.137.1 (ICS gateway).
LAPTOP_HOST = os.environ.get("DARKMAP_LAPTOP_HOST", "192.168.137.1")
LAPTOP_PORT = int(os.environ.get("DARKMAP_LAPTOP_PORT", "9009"))
RECONNECT_SEC = float(os.environ.get("DARKMAP_RECONNECT_SEC", "2.0"))

_sock: Optional[socket.socket] = None


def _log(msg: str) -> None:
    print(f"[forwarder] {msg}", flush=True)


def _close_socket() -> None:
    global _sock
    if _sock is not None:
        try:
            _sock.close()
        except OSError:
            pass
        _sock = None


def _ensure_connected() -> socket.socket:
    """Return an open TCP socket to the laptop, reconnecting on failure."""
    global _sock
    while _sock is None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((LAPTOP_HOST, LAPTOP_PORT))
            _sock = s
            _log(f"connected to {LAPTOP_HOST}:{LAPTOP_PORT}")
        except OSError as exc:
            _log(f"connect failed ({exc}); retry in {RECONNECT_SEC:.0f}s")
            time.sleep(RECONNECT_SEC)
    return _sock


def on_telemetry(line: str) -> None:
    """Bridge callback: forward one CSV telemetry line to the laptop."""
    if not line or not str(line).strip():
        return
    payload = str(line).strip() + "\n"
    global _sock
    try:
        _ensure_connected().sendall(payload.encode("utf-8"))
    except OSError as exc:
        _log(f"send failed ({exc}); will reconnect")
        _close_socket()


def idle_loop() -> None:
    """Keep the App Lab process alive between Bridge callbacks."""
    time.sleep(1.0)


def main() -> None:
    _log(f"target laptop {LAPTOP_HOST}:{LAPTOP_PORT}")
    Bridge.provide("telemetry", on_telemetry)
    _log("Bridge.provide('telemetry') registered; waiting for MCU data")
    App.run(user_loop=idle_loop)


if __name__ == "__main__":
    main()
