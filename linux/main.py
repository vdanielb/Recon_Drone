#!/usr/bin/env python3
"""DARKMAP-Q - Linux/MPU side orchestrator.

Reads CSV telemetry from the MCU (or a simulator/file), parses SCAN / MOVE /
STATE packets, updates a dead-reckoning pose estimate, builds a 2D obstacle
map, logs the raw session to CSV, and optionally shows a live map. Runs fully
offline - no cloud APIs.

Examples
--------
    # No hardware: synthetic 'rover in a box' demo with a live map
    python3 main.py --source sim

    # No hardware, headless (CI / quick check), no plotting window
    python3 main.py --source sim --no-plot

    # Live rover over serial
    python3 main.py --source serial --port /dev/ttyACM0

    # Replay a saved session log
    python3 main.py --source file --file data/logs/session_XXXX.csv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional

# Allow running from repo root or from inside linux/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mapper import Mapper, LiveMap  # noqa: E402
from scene import classify, risk_level  # noqa: E402
from serial_bridge import make_source  # noqa: E402


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_log_dir() -> str:
    return os.path.join(_repo_root(), "data", "logs")


def parse_line(line: str):
    """Parse one CSV telemetry line into a tuple (kind, fields...) or None."""
    parts = [p.strip() for p in line.split(",")]
    if not parts or not parts[0]:
        return None
    kind = parts[0].upper()

    try:
        if kind == "SCAN" and len(parts) >= 5:
            # SCAN,timestamp_ms,angle_deg,distance_cm,mode
            return ("SCAN", int(parts[2]), float(parts[3]), parts[4])
        if kind == "MOVE" and len(parts) >= 5:
            # MOVE,timestamp_ms,action,duration_ms,speed
            return ("MOVE", parts[2], float(parts[3]), float(parts[4]))
        if kind == "STATE" and len(parts) >= 4:
            # STATE,timestamp_ms,mode,message
            return ("STATE", parts[2], parts[3])
    except (ValueError, IndexError):
        return None
    return None


def run(args: argparse.Namespace) -> int:
    log_dir = args.log_dir or _default_log_dir()
    os.makedirs(log_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_path = os.path.join(log_dir, f"session_{stamp}.csv")
    map_png = os.path.join(log_dir, "map.png")
    status_path = os.path.join(log_dir, "status.json")
    points_csv = os.path.join(log_dir, f"points_{stamp}.csv")

    def write_status(mode: str, scene: str) -> None:
        try:
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump({
                    "mode": mode,
                    "scene": scene,
                    "last_distance_cm": mapper.last_distance_cm,
                    "obstacles": len(mapper.obstacle_points),
                    "pose": [round(mapper.pose.x, 1), round(mapper.pose.y, 1)],
                }, fh)
        except OSError:
            pass

    mapper = Mapper()
    live = None if args.no_plot else LiveMap(mapper, redraw_every=args.redraw_every)

    current_mode = "STOP"
    scan_since_classify = 0
    sweeps_since_png = 0

    print(f"[main] DARKMAP-Q offline mapper - source={args.source}")
    print(f"[main] session log -> {session_path}")

    log_fh = open(session_path, "w", encoding="utf-8")
    try:
        with make_source(args.source, port=args.port, file=args.file,
                         sim_steps=args.sim_steps, delay=args.delay) as source:
            for line in source.lines():
                if not line:
                    continue
                log_fh.write(line + "\n")
                log_fh.flush()

                parsed = parse_line(line)
                if parsed is None:
                    continue

                kind = parsed[0]
                if kind == "SCAN":
                    _, angle, dist, mode = parsed
                    current_mode = mode or current_mode
                    added = mapper.add_scan(angle, dist)
                    scan_since_classify += 1

                    if angle == 0 and dist >= 0:
                        rl = risk_level(dist)
                        if rl == "HIGH":
                            print(f"[risk] HIGH - obstacle {dist:.0f}cm ahead")

                    # Classify roughly once per full sweep.
                    if scan_since_classify >= 7:
                        scan_since_classify = 0
                        sweeps_since_png += 1
                        label = classify(mapper.last_scan)
                        write_status(current_mode, label)
                        # Refresh the saved PNG occasionally (for the dashboard).
                        # Rendering is relatively expensive, so throttle it.
                        if sweeps_since_png >= args.png_every:
                            sweeps_since_png = 0
                            mapper.save_map(map_png)
                        print(f"[scene] {label:<13} "
                              f"pose=({mapper.pose.x:6.1f},{mapper.pose.y:6.1f}) "
                              f"obstacles={len(mapper.obstacle_points)}")
                    if added and live:
                        live.notify()

                elif kind == "MOVE":
                    _, action, dur, speed = parsed
                    mapper.apply_move(action, dur, speed)
                    if live:
                        live.notify()

                elif kind == "STATE":
                    _, mode, message = parsed
                    current_mode = mode or current_mode
                    print(f"[state] mode={current_mode} :: {message}")

    except KeyboardInterrupt:
        print("\n[main] interrupted by user; finalizing...")
    finally:
        log_fh.close()
        # Always try to persist results.
        mapper.save_points_csv(points_csv)
        saved = mapper.save_map(map_png)
        print(f"[main] points  -> {points_csv}")
        if saved:
            print(f"[main] map png -> {saved}")
        print(f"[main] final pose=({mapper.pose.x:.1f},{mapper.pose.y:.1f}) "
              f"theta={mapper.pose.theta:.2f}rad  "
              f"obstacles={len(mapper.obstacle_points)}  "
              f"path_pts={len(mapper.path_points)}")
        if live and args.hold:
            print("[main] close the plot window to exit.")
            live.hold()

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DARKMAP-Q offline mapping app")
    p.add_argument("--source", default="sim",
                   choices=["serial", "file", "stdin", "sim"],
                   help="telemetry source (default: sim)")
    p.add_argument("--port", default=None,
                   help="serial port (e.g. /dev/ttyACM0); auto-detect if omitted")
    p.add_argument("--file", default=None,
                   help="path to a saved session log (for --source file)")
    p.add_argument("--no-plot", action="store_true",
                   help="disable the live matplotlib window (headless)")
    p.add_argument("--hold", action="store_true",
                   help="keep the plot window open after the stream ends")
    p.add_argument("--redraw-every", type=int, default=7,
                   help="redraw the live map every N updates (default: 7)")
    p.add_argument("--png-every", type=int, default=5,
                   help="resave map.png every N sweeps for the dashboard (default: 5)")
    p.add_argument("--sim-steps", type=int, default=120,
                   help="number of steps for the simulator (default: 120)")
    p.add_argument("--delay", type=float, default=0.03,
                   help="delay between sim/file lines in seconds (default: 0.03)")
    p.add_argument("--log-dir", default=None,
                   help="override the log directory (default: data/logs)")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
