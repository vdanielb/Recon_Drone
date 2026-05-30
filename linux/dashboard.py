#!/usr/bin/env python3
"""Optional offline local dashboard for DARKMAP-Q.

Serves a tiny web page (on localhost, no cloud) that shows the latest saved
map image, the most recent scan distance, the current mode, and an
"offline / no cloud" status badge. This is intentionally minimal and reads
from the shared status that ``main.py`` writes.

Two ways to use it:

1. Standalone viewer of the last saved map (simplest for a demo):
       python3 dashboard.py
   It auto-refreshes and renders data/logs/map.png plus the latest status.

2. Programmatic status updates: import and call ``update_status(...)`` from
   another process is not supported across processes; instead the dashboard
   reads data/logs/status.json if present. ``main.py`` does not require this,
   so the dashboard degrades gracefully when the file is missing.

Run:
    pip install Flask
    python3 dashboard.py --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "data", "logs")
MAP_PNG = os.path.join(LOG_DIR, "map.png")
STATUS_JSON = os.path.join(LOG_DIR, "status.json")


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="2"/>
  <title>DARKMAP-Q Dashboard</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
            background:#0d1117; color:#e6edf3; margin:0; padding:24px; }}
    h1 {{ margin:0 0 4px 0; font-size:22px; letter-spacing:1px; }}
    .sub {{ color:#8b949e; margin-bottom:18px; }}
    .grid {{ display:flex; gap:24px; flex-wrap:wrap; }}
    .card {{ background:#161b22; border:1px solid #30363d; border-radius:10px;
             padding:16px 18px; min-width:180px; }}
    .label {{ color:#8b949e; font-size:12px; text-transform:uppercase; }}
    .value {{ font-size:26px; font-weight:600; margin-top:4px; }}
    .badge {{ display:inline-block; padding:4px 10px; border-radius:999px;
              background:#1f6feb33; color:#58a6ff; font-size:12px; }}
    .offline {{ background:#23863633; color:#3fb950; }}
    img {{ max-width:100%; border:1px solid #30363d; border-radius:10px;
           background:#fff; }}
    .map {{ margin-top:20px; }}
  </style>
</head>
<body>
  <h1>DARKMAP-Q</h1>
  <div class="sub">Offline GPS-denied reconnaissance mapping &mdash; local dashboard</div>
  <div class="grid">
    <div class="card"><div class="label">Mode</div>
      <div class="value">{mode}</div></div>
    <div class="card"><div class="label">Last distance</div>
      <div class="value">{distance}</div></div>
    <div class="card"><div class="label">Scene</div>
      <div class="value">{scene}</div></div>
    <div class="card"><div class="label">Connectivity</div>
      <div class="value"><span class="badge offline">OFFLINE / NO CLOUD</span></div></div>
  </div>
  <div class="map">
    <div class="label">Latest map ({updated})</div><br/>
    {map_html}
  </div>
</body>
</html>"""


def _read_status() -> dict:
    if os.path.exists(STATUS_JSON):
        try:
            with open(STATUS_JSON, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def render_page() -> str:
    status = _read_status()
    if os.path.exists(MAP_PNG):
        ts = datetime.fromtimestamp(os.path.getmtime(MAP_PNG)).strftime("%H:%M:%S")
        # Cache-bust so the auto-refresh actually shows new frames.
        map_html = f'<img src="/map.png?ts={int(os.path.getmtime(MAP_PNG))}"/>'
    else:
        ts = "n/a"
        map_html = '<div class="sub">No map yet. Run main.py to generate one.</div>'

    dist = status.get("last_distance_cm")
    dist_str = f"{dist:.0f} cm" if isinstance(dist, (int, float)) and dist >= 0 else "--"
    return PAGE.format(
        mode=status.get("mode", "--"),
        distance=dist_str,
        scene=status.get("scene", "--"),
        updated=ts,
        map_html=map_html,
    )


def create_app():
    try:
        from flask import Flask, Response, send_file
    except ImportError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(
            "Flask is required for the dashboard. Install with: pip install Flask"
        ) from exc

    app = Flask(__name__)

    @app.route("/")
    def index():
        return Response(render_page(), mimetype="text/html")

    @app.route("/map.png")
    def map_png():
        if os.path.exists(MAP_PNG):
            return send_file(MAP_PNG, mimetype="image/png")
        return Response("no map", status=404)

    return app


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="DARKMAP-Q local dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    app = create_app()
    print(f"[dashboard] serving on http://{args.host}:{args.port} (offline)")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
