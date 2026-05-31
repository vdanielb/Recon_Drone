#!/usr/bin/env python3
"""Standalone webcam + YOLO test for DARKMAP-Q (no telemetry needed).

Use this to verify the camera and model work on their own before wiring
detection into the full app.

Examples
--------
    # Continuous: print mission-class detections every frame (Ctrl-C to stop)
    python3 test_detector.py

    # Single frame, then exit
    python3 test_detector.py --once

    # Show an annotated preview window (needs a display + cv2 GUI support)
    python3 test_detector.py --show

    # Pick a different camera / model / confidence
    python3 test_detector.py --camera 1 --model yolov8n.pt --conf 0.5

Exit codes: 0 if the detector is available and ran; 1 if it could not start
(missing deps, no camera, or model load failure).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector import Detector, CATEGORY_OF, display_label  # noqa: E402

_LINUX_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT  = os.path.dirname(_LINUX_DIR)
_DEFAULT_FRAME_PATH = os.path.join(_REPO_ROOT, "data", "logs", "camera_frame.jpg")


def _print_categories() -> None:
    print("[test] mission classes -> categories:")
    by_cat: dict = {}
    for coco, cat in CATEGORY_OF.items():
        by_cat.setdefault(cat, []).append(display_label(coco))
    for cat, labels in by_cat.items():
        print(f"        {cat:<12} {', '.join(sorted(labels))}")


def run(args: argparse.Namespace) -> int:
    _print_categories()
    print(f"[test] opening camera {args.camera} with model {args.model} "
          f"(conf>={args.conf}) ...")

    frame_path = None if args.no_save_frames else _DEFAULT_FRAME_PATH
    if frame_path:
        os.makedirs(os.path.dirname(frame_path), exist_ok=True)
        print(f"[test] saving frames -> {frame_path}  (use --no-save-frames to disable)")

    det = Detector(camera_index=args.camera, model_path=args.model,
                   conf=args.conf, frame_save_path=frame_path)

    if not det.available:
        print(f"[test] detector UNAVAILABLE: {det.error}")
        print("[test] install extras with: pip install opencv-python ultralytics")
        return 1

    det.start()
    print("[test] detector running. Press Ctrl-C to stop.")

    show = args.show
    cv2 = det._cv2  # already imported and guarded inside Detector

    try:
        frames = 0
        while True:
            time.sleep(0.2)
            dets = det.get_latest()
            frames += 1

            if dets:
                summary = ", ".join(
                    f"{d['category']}:{d['label']} {d['confidence']:.0%}"
                    for d in dets
                )
                print(f"[det] {summary}")
            else:
                print("[det] (no mission objects)")

            if show and cv2 is not None and det._cap is not None:
                ok, frame = det._cap.read()
                if ok and frame is not None:
                    for d in dets:
                        cv2.putText(frame,
                                    f"{d['category']}:{d['label']} {d['confidence']:.0%}",
                                    (10, 30 + 24 * dets.index(d)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    (0, 255, 180), 2)
                    cv2.imshow("DARKMAP-Q detector test", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

            if args.once:
                break

    except KeyboardInterrupt:
        print("\n[test] stopping...")
    finally:
        det.stop()
        if show and cv2 is not None:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        print(f"[test] done. fps≈{det.stats()['fps']}")

    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="DARKMAP-Q standalone detector test")
    p.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    p.add_argument("--model", default="yolov8n.pt", help="YOLO model path/name")
    p.add_argument("--conf", type=float, default=0.45, help="confidence threshold")
    p.add_argument("--show", action="store_true",
                   help="show annotated preview window (needs display)")
    p.add_argument("--once", action="store_true",
                   help="run a single frame then exit")
    p.add_argument("--no-save-frames", action="store_true",
                   help="disable saving annotated frames for the dashboard "
                        f"(default saves to data/logs/camera_frame.jpg)")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
