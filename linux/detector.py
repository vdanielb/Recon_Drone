"""Offline YOLO reconnaissance object detector for DARKMAP-Q.

This module pairs the rover's ultrasonic distance sensing (WHERE something is)
with a camera + YOLO classifier (WHAT it is). It runs Ultralytics YOLO
(yolov8n by default) on frames grabbed via OpenCV, filters results down to a
small set of mission-relevant classes, groups them into recon categories, and
exposes the latest detections to the main app.

Design goals
------------
- **Never crash the caller.** All heavy imports (cv2, ultralytics) and every
  camera/model operation are guarded. If anything is missing or fails,
  ``Detector.available`` becomes False and the rest of DARKMAP-Q runs normally.
- **Never block the telemetry loop.** Inference runs in a daemon background
  thread; the main loop only reads the latest result list (lock-protected).
- **Offline.** Inference is fully local. Only the first-ever model download
  needs internet; after that ``yolov8n.pt`` is cached on disk.

Neutral recon only: detections are tagged for review. Nothing here labels
anything as a weapon, threat, or danger.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Mission classes and recon categories (single source of truth)
#
# Keys are COCO class names as emitted by YOLO; values are our recon category.
# Only these classes are kept; every other COCO class is ignored.
# ---------------------------------------------------------------------------
CATEGORY_OF: Dict[str, str] = {
    # human
    "person": "human",
}

# Friendly label overrides for display (COCO name -> recon label).
DISPLAY_LABEL: Dict[str, str] = {
    "dining table": "table",
    "cell phone": "phone",
}

MISSION_CLASSES = set(CATEGORY_OF.keys())

# Standard COCO 80-class names in index order (used by ONNX backend when the
# model metadata does not embed a names map).
_COCO80_NAMES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
    5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
    10: "fire hydrant", 11: "stop sign", 12: "parking meter", 13: "bench",
    14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
    20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe", 24: "backpack",
    25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase", 29: "frisbee",
    30: "skis", 31: "snowboard", 32: "sports ball", 33: "kite",
    34: "baseball bat", 35: "baseball glove", 36: "skateboard", 37: "surfboard",
    38: "tennis racket", 39: "bottle", 40: "wine glass", 41: "cup", 42: "fork",
    43: "knife", 44: "spoon", 45: "bowl", 46: "banana", 47: "apple",
    48: "sandwich", 49: "orange", 50: "broccoli", 51: "carrot", 52: "hot dog",
    53: "pizza", 54: "donut", 55: "cake", 56: "chair", 57: "couch",
    58: "potted plant", 59: "bed", 60: "dining table", 61: "toilet", 62: "tv",
    63: "laptop", 64: "mouse", 65: "remote", 66: "keyboard", 67: "cell phone",
    68: "microwave", 69: "oven", 70: "toaster", 71: "sink", 72: "refrigerator",
    73: "book", 74: "clock", 75: "vase", 76: "scissors", 77: "teddy bear",
    78: "hair drier", 79: "toothbrush",
}


def display_label(coco_name: str) -> str:
    return DISPLAY_LABEL.get(coco_name, coco_name)


class Detector:
    """Background-thread YOLO detector with graceful degradation.

    Usage::

        det = Detector(camera_index=0)
        det.start()
        ...
        for d in det.get_latest():
            print(d["category"], d["label"], d["confidence"])
        ...
        det.stop()
    """

    def __init__(self, camera_index: int = 0, model_path: str = "yolov8n.pt",
                 conf: float = 0.45, hfov_deg: float = 60.0,
                 imgsz: int = 416) -> None:
        self.camera_index = camera_index
        self.model_path = model_path
        self.conf = conf
        self.hfov_deg = hfov_deg
        self.imgsz = imgsz

        self.available = False
        self.error: Optional[str] = None

        self._cv2 = None
        self._model = None          # Ultralytics YOLO (set by _init_ultralytics_backend)
        self._session = None        # onnxruntime InferenceSession (set by _init_onnx_backend)
        self._np = None             # numpy ref for ONNX backend
        self._ort_input_name = ""
        self._ort_names: dict = {}
        self._backend = "ultralytics"  # "ultralytics" | "onnx"
        self._cap = None

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: List[dict] = []

        # Stats
        self._fps = 0.0
        self._frames = 0

        self._init_backend()

    # ----- initialization (fully guarded) ---------------------------------
    def _init_backend(self) -> None:
        try:
            import cv2  # type: ignore
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"opencv-python not available: {exc}"
            return

        self._cv2 = cv2

        if self.model_path.endswith(".onnx"):
            self._init_onnx_backend()
        else:
            self._init_ultralytics_backend()

    # ----- ONNX Runtime backend (edge / no Ultralytics needed) ---------------
    def _init_onnx_backend(self) -> None:
        try:
            import onnxruntime as ort  # type: ignore
            import numpy as np  # type: ignore
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"onnxruntime not available: {exc}"
            return

        if not os.path.exists(self.model_path):
            self.error = f"ONNX model not found: {self.model_path}"
            return

        try:
            self._session = ort.InferenceSession(
                self.model_path,
                providers=["CPUExecutionProvider"],
            )
            self._np = np
            inp = self._session.get_inputs()[0]
            self._ort_input_name = inp.name
            # Derive imgsz from the model's declared input shape if available.
            shape = inp.shape  # e.g. [1, 3, 416, 416]
            if isinstance(shape, (list, tuple)) and len(shape) == 4:
                h, w = shape[2], shape[3]
                if isinstance(h, int) and h > 0:
                    self.imgsz = h  # override constructor default

            # Load COCO class names from metadata or use the standard 80-class list.
            meta = self._session.get_modelmeta().custom_metadata_map
            names_str = meta.get("names", "")
            if names_str:
                import ast
                self._ort_names = ast.literal_eval(names_str)
            else:
                self._ort_names = _COCO80_NAMES
            self._backend = "onnx"
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"ONNX session load failed: {exc}"
            return

        try:
            cap = self._cv2.VideoCapture(self.camera_index)
            if not cap or not cap.isOpened():
                self.error = f"camera index {self.camera_index} could not be opened"
                if cap:
                    cap.release()
                return
            self._cap = cap
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"camera open error: {exc}"
            return

        self.available = True

    # ----- Ultralytics backend (dev / full model) ----------------------------
    def _init_ultralytics_backend(self) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"ultralytics not available: {exc}"
            return

        try:
            # First call may download yolov8n.pt (one-time, needs internet).
            self._model = YOLO(self.model_path)
            self._backend = "ultralytics"
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"failed to load model {self.model_path!r}: {exc}"
            return

        try:
            cap = self._cv2.VideoCapture(self.camera_index)
            if not cap or not cap.isOpened():
                self.error = f"camera index {self.camera_index} could not be opened"
                if cap:
                    cap.release()
                return
            self._cap = cap
        except Exception as exc:  # pragma: no cover - env dependent
            self.error = f"camera open error: {exc}"
            return

        self.available = True

    # ----- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        """Start the inference thread. Returns True if running."""
        if not self.available:
            return False
        if self._thread is not None:
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="darkmapq-detector")
        self._thread.start()
        return True

    def stop(self) -> None:
        """Signal the thread to stop, join briefly, release the camera."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    # ----- background inference loop ---------------------------------------
    def _run(self) -> None:
        last_t = time.time()
        while not self._stop.is_set():
            try:
                ok, frame = self._cap.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                # Camera hiccup: back off briefly, keep trying.
                time.sleep(0.05)
                continue

            detections = self._infer(frame)
            with self._lock:
                self._latest = detections

            self._frames += 1
            now = time.time()
            dt = now - last_t
            if dt > 0:
                # Exponential moving average for a stable FPS readout.
                self._fps = 0.8 * self._fps + 0.2 * (1.0 / dt) if self._fps else 1.0 / dt
            last_t = now

    def _infer(self, frame) -> List[dict]:
        """Dispatch to the active backend."""
        if self._backend == "onnx":
            return self._infer_onnx(frame)
        return self._infer_ultralytics(frame)

    def _infer_ultralytics(self, frame) -> List[dict]:
        """Run YOLO on one frame using the Ultralytics backend."""
        try:
            results = self._model(frame, conf=self.conf, imgsz=self.imgsz,
                                   verbose=False)
        except Exception:
            return []

        out: List[dict] = []
        try:
            width = frame.shape[1] or 1
        except Exception:
            width = 1

        for res in results:
            names = getattr(res, "names", {}) or {}
            boxes = getattr(res, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                try:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    coco_name = names.get(cls_id, str(cls_id))
                except Exception:
                    continue
                if coco_name not in MISSION_CLASSES:
                    continue
                cx_frac = 0.5
                try:
                    x1, _, x2, _ = (float(v) for v in box.xyxy[0])
                    cx_frac = min(1.0, max(0.0, ((x1 + x2) / 2.0) / width))
                except Exception:
                    pass
                out.append({
                    "label": display_label(coco_name),
                    "coco": coco_name,
                    "category": CATEGORY_OF[coco_name],
                    "confidence": round(conf, 3),
                    "bbox_cx_frac": round(cx_frac, 3),
                })
        return out

    def _infer_onnx(self, frame) -> List[dict]:
        """Run inference using the ONNX Runtime backend.

        YOLOv8 ONNX output: (1, 84, N) where 84 = 4 box coords + 80 class
        scores, N = number of anchor points.  Boxes are in cx,cy,w,h format
        normalised to [0,1].  This method:
          1. Pre-processes the frame to (1,3,H,W) float32.
          2. Runs the session.
          3. Post-processes: filter by score, NMS, map class id -> mission class.
        """
        np = self._np
        cv2 = self._cv2
        h = w = self.imgsz
        try:
            blob = cv2.resize(frame, (w, h))
            blob = blob[:, :, ::-1].astype(np.float32) / 255.0   # BGR->RGB, 0-1
            blob = blob.transpose(2, 0, 1)[np.newaxis]           # HWC -> NCHW
        except Exception:
            return []

        try:
            raw = self._session.run(None, {self._ort_input_name: blob})
        except Exception:
            return []

        try:
            # raw[0]: (1, 84, N) -> (N, 84)
            pred = raw[0][0].T  # (N, 84)
            boxes_xywh = pred[:, :4]
            class_scores = pred[:, 4:]    # (N, 80)

            max_scores = class_scores.max(axis=1)
            mask = max_scores >= self.conf
            if not mask.any():
                return []

            boxes_xywh = boxes_xywh[mask]
            class_scores = class_scores[mask]
            max_scores = max_scores[mask]
            class_ids = class_scores.argmax(axis=1)

            orig_h, orig_w = frame.shape[:2]
            # Convert cx,cy,w,h (normalised to imgsz) -> x1,y1,x2,y2 (pixels in orig frame)
            cx = boxes_xywh[:, 0] / w * orig_w
            cy = boxes_xywh[:, 1] / h * orig_h
            bw = boxes_xywh[:, 2] / w * orig_w
            bh = boxes_xywh[:, 3] / h * orig_h
            x1s = (cx - bw / 2).tolist()
            y1s = (cy - bh / 2).tolist()
            bws = bw.tolist()
            bhs = bh.tolist()

            # OpenCV NMS expects int rects
            rects = [[int(x), int(y), int(bw_), int(bh_)]
                     for x, y, bw_, bh_ in zip(x1s, y1s, bws, bhs)]
            indices = cv2.dnn.NMSBoxes(rects, max_scores.tolist(),
                                       self.conf, 0.45)
            if len(indices) == 0:
                return []
            indices = indices.flatten()
        except Exception:
            return []

        out: List[dict] = []
        for idx in indices:
            cls_id = int(class_ids[idx])
            coco_name = self._ort_names.get(cls_id, str(cls_id))
            if coco_name not in MISSION_CLASSES:
                continue
            conf_val = float(max_scores[idx])
            x1 = x1s[idx]
            cx_frac = min(1.0, max(0.0, (x1 + bws[idx] / 2) / orig_w))
            out.append({
                "label": display_label(coco_name),
                "coco": coco_name,
                "category": CATEGORY_OF[coco_name],
                "confidence": round(conf_val, 3),
                "bbox_cx_frac": round(cx_frac, 3),
            })
        return out

    # ----- read API --------------------------------------------------------
    def get_latest(self) -> List[dict]:
        """Return (a copy of) the most recent detection list."""
        with self._lock:
            return list(self._latest)

    def bearing_deg(self, bbox_cx_frac: float) -> float:
        """Map a horizontal bbox center (0..1) to a bearing offset in degrees.

        Camera center (0.5) -> 0 deg. Left of frame -> positive (left = +,
        matching the rover/servo convention). Right of frame -> negative.
        """
        return (0.5 - bbox_cx_frac) * self.hfov_deg

    def stats(self) -> dict:
        return {
            "enabled": self.available and self._thread is not None,
            "available": self.available,
            "model": self.model_path,
            "backend": self._backend,
            "camera": self.camera_index,
            "fps": round(self._fps, 1),
            "error": self.error,
        }
