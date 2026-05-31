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
import csv
import json
import math
import os
import sys
import time
from datetime import datetime
from typing import List, Optional

# Allow running from repo root or from inside linux/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mapper import Mapper, LiveMap  # noqa: E402
from scene import classify, risk_level  # noqa: E402
from serial_bridge import make_source  # noqa: E402

# Detector is optional; guard the import so the app runs without cv2/ultralytics.
try:
    from detector import Detector  # noqa: E402
except Exception:  # pragma: no cover - import guarded for safety
    Detector = None  # type: ignore


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
        if kind == "HEADING" and len(parts) >= 3:
            # HEADING,timestamp_ms,yaw_deg
            return ("HEADING", float(parts[2]))
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
    detections_csv = os.path.join(log_dir, f"detections_{stamp}.csv")

    recent_events: List[dict] = []
    last_action: Optional[str] = None
    MAX_EVENTS = 20

    # ----- recon detection state ------------------------------------------
    detector = None
    if not args.no_detect and Detector is not None:
        detector = Detector(camera_index=args.camera, model_path=args.model,
                            conf=args.detect_conf,
                            frame_save_path=os.path.join(log_dir, "camera_frame.jpg"))
        if detector.available:
            detector.start()
            print(f"[detect] camera {args.camera} + {args.model} active")
        else:
            print(f"[detect] disabled: {detector.error}")
            detector = None
    elif not args.no_detect and Detector is None:
        print("[detect] disabled: opencv-python / ultralytics not installed")

    recent_detections: List[dict] = []   # last N for status.json
    detection_counts: dict = {}
    cat_last_seen: dict = {}             # category -> monotonic time (cooldown)
    MAX_RECENT_DET = 12

    det_fh = open(detections_csv, "w", newline="", encoding="utf-8")
    det_writer = csv.writer(det_fh)
    det_writer.writerow(["timestamp", "category", "label", "confidence",
                         "distance_cm", "x_cm", "y_cm", "note"])

    def _front_distance() -> Optional[float]:
        for angle, dist in reversed(mapper.last_scan):
            if angle == 0 and dist is not None and dist >= 0:
                return float(dist)
        return None

    def append_event(message: str) -> None:
        recent_events.insert(0, {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "msg": message,
        })
        del recent_events[MAX_EVENTS:]

    def write_status(mode: str, scene: Optional[str] = None) -> None:
        if scene is not None:
            nonlocal current_scene
            current_scene = scene
        front = _front_distance()
        risk = risk_level(front) if front is not None else "CLEAR"
        try:
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump({
                    "mode": mode,
                    "scene": current_scene,
                    "risk": risk,
                    "last_distance_cm": mapper.last_distance_cm,
                    "front_distance_cm": front,
                    "obstacles": len(mapper.obstacle_points),
                    "path_points": len(mapper.path_points),
                    "pose": [round(mapper.pose.x, 1), round(mapper.pose.y, 1)],
                    "theta_deg": round(math.degrees(mapper.pose.theta), 1),
                    "last_scan": [[a, d] for a, d in mapper.last_scan],
                    "last_action": last_action,
                    "events": recent_events,
                    "updated": datetime.now().strftime("%H:%M:%S"),
                    "path": [[round(x, 1), round(y, 1)] for x, y in mapper.path_points],
                    "obstacle_xy": [
                        [round(x, 1), round(y, 1)] for x, y in mapper.obstacle_points
                    ],
                    # ----- recon detection (additive; absent fields are fine) -----
                    "detections": recent_detections,
                    "detection_tags": [
                        {"x": t["x"], "y": t["y"], "category": t["category"],
                         "label": t["label"], "conf": t["conf"],
                         "note": t.get("note", "")}
                        for t in mapper.detection_tags[-200:]
                    ],
                    "detection_counts": detection_counts,
                    "detector": detector.stats() if detector is not None
                    else {"enabled": False, "available": False},
                    "imu": {
                        "enabled": mapper._imu_heading,
                        "yaw_deg": imu_yaw_deg,
                        "ok": mapper._imu_heading,
                    },
                }, fh)
        except OSError:
            pass

    mapper = Mapper()
    live = None if args.no_plot else LiveMap(mapper, redraw_every=args.redraw_every)

    current_mode = "STOP"
    current_scene = "UNKNOWN"
    imu_yaw_deg: Optional[float] = None
    scan_since_classify = 0
    sweeps_since_png = 0

    def poll_detections() -> bool:
        """Pull the latest camera detections and tag them on the map.

        A per-category cooldown prevents the same object from spamming the
        map every frame. Placement uses the latest front ultrasonic distance;
        if none is available the tag is marked distance_unknown. Returns True
        if any new tag was added.
        """
        if detector is None:
            return False
        added = False
        front = _front_distance()
        now = time.monotonic()
        for d in detector.get_latest():
            cat = d["category"]
            if now - cat_last_seen.get(cat, -1e9) < args.detect_cooldown:
                continue
            cat_last_seen[cat] = now

            bearing = detector.bearing_deg(d.get("bbox_cx_frac", 0.5))
            tag = mapper.add_detection_tag(cat, d["label"], d["confidence"],
                                           front, bearing_deg=bearing)
            detection_counts[cat] = detection_counts.get(cat, 0) + 1

            rec = {
                "ts": datetime.now().strftime("%H:%M:%S"),
                "category": cat,
                "label": d["label"],
                "conf": d["confidence"],
                "distance_cm": front,
                "x": tag["x"],
                "y": tag["y"],
                "note": tag.get("note", ""),
            }
            recent_detections.insert(0, rec)
            del recent_detections[MAX_RECENT_DET:]

            dist_str = f"{front:.0f}cm" if front is not None else "dist?"
            append_event(f"DET {cat}:{d['label']} {d['confidence']:.0%} @ {dist_str}")
            det_writer.writerow([
                datetime.now().isoformat(timespec="seconds"), cat, d["label"],
                f"{d['confidence']:.3f}",
                "" if front is None else f"{front:.1f}",
                f"{tag['x']:.1f}", f"{tag['y']:.1f}", tag.get("note", ""),
            ])
            det_fh.flush()
            print(f"[detect] {cat}:{d['label']} {d['confidence']:.0%} @ {dist_str}")
            added = True
        return added

    print(f"[main] DARKMAP-Q offline mapper - source={args.source}"
          + (f"  room={args.room}" if args.room else ""))
    print(f"[main] session log -> {session_path}")

    log_fh = open(session_path, "w", encoding="utf-8")
    try:
        with make_source(args.source, port=args.port, file=args.file,
                         sim_steps=args.sim_steps, delay=args.delay,
                         room=args.room,
                         listen_host=args.listen_host,
                         listen_port=args.listen_port) as source:
            for line in source.lines():
                # Camera detections run asynchronously; fold in any new tags.
                if poll_detections():
                    write_status(current_mode)
                    if live:
                        live.notify()

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

                    if added or scan_since_classify >= 7:
                        if scan_since_classify >= 7:
                            scan_since_classify = 0
                            sweeps_since_png += 1
                            label = classify(mapper.last_scan, mode=current_mode)
                            write_status(current_mode, scene=label)
                            if sweeps_since_png >= args.png_every:
                                sweeps_since_png = 0
                                mapper.save_map(map_png)
                            print(f"[scene] {label:<13} "
                                  f"pose=({mapper.pose.x:6.1f},{mapper.pose.y:6.1f}) "
                                  f"obstacles={len(mapper.obstacle_points)}")
                        else:
                            write_status(current_mode)
                    if added and live:
                        live.notify()

                elif kind == "MOVE":
                    _, action, dur, speed = parsed
                    mapper.apply_move(action, dur, speed)
                    last_action = f"{action} {dur:.0f}ms"
                    append_event(last_action)
                    write_status(current_mode)
                    if live:
                        live.notify()

                elif kind == "HEADING":
                    _, yaw = parsed
                    imu_yaw_deg = yaw
                    mapper.set_heading(yaw)
                    write_status(current_mode)

                elif kind == "STATE":
                    _, mode, message = parsed
                    current_mode = mode or current_mode
                    append_event(message)
                    write_status(current_mode)
                    print(f"[state] mode={current_mode} :: {message}")

    except KeyboardInterrupt:
        print("\n[main] interrupted by user; finalizing...")
    finally:
        if detector is not None:
            detector.stop()
        log_fh.close()
        det_fh.close()
        # Drop the detections CSV if nothing was ever detected (header only).
        if not mapper.detection_tags:
            try:
                os.remove(detections_csv)
            except OSError:
                pass
        # Always try to persist results.
        mapper.save_points_csv(points_csv)
        saved = mapper.save_map(map_png)
        print(f"[main] points  -> {points_csv}")
        if mapper.detection_tags:
            print(f"[main] detections -> {detections_csv} "
                  f"({len(mapper.detection_tags)} tags)")
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
                   choices=["serial", "file", "stdin", "sim", "wallsim", "net"],
                   help="telemetry source (default: sim); "
                        "use 'wallsim' to simulate WALLFOLLOW; "
                        "use 'net' for WiFi TCP from the UNO Q board")
    p.add_argument("--port", default=None,
                   help="serial port (e.g. /dev/ttyACM0); auto-detect if omitted")
    p.add_argument("--listen-host", default="0.0.0.0",
                   help="bind address for --source net (default: 0.0.0.0)")
    p.add_argument("--listen-port", type=int, default=9009,
                   help="TCP port for --source net (default: 9009)")
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
    # ----- recon object detection (camera + YOLO) -----
    p.add_argument("--no-detect", action="store_true",
                   help="disable camera/YOLO recon detection (on by default if available)")
    p.add_argument("--camera", type=int, default=0,
                   help="camera index for detection (default: 0)")
    p.add_argument("--model", default="yolov8n.pt",
                   help="YOLO model path/name for detection (default: yolov8n.pt)")
    p.add_argument("--detect-conf", type=float, default=0.45,
                   help="detection confidence threshold (default: 0.45)")
    p.add_argument("--detect-cooldown", type=float, default=3.0,
                   help="seconds between map tags per category (default: 3.0)")
    p.add_argument("--room", default=None,
                   help=(
                       "room shape for --source wallsim. "
                       "Formats: "
                       "square (300cm default), "
                       "square:N, "
                       "rect:WxH (e.g. rect:500x300), "
                       "circle, circle:N, circle:N:S (diameter cm, segments), "
                       "triangle, triangle:N (equilateral side cm), "
                       "l-shape, "
                       "poly:x1,y1,x2,y2,... (custom polygon vertices in cm). "
                       "Default: square"
                   ))
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
