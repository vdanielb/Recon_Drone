"""Export YOLOv8n to ONNX FP32, then quantize to INT8 for edge deployment.

Run once on a development machine that has Ultralytics + PyTorch installed.
The resulting INT8 ONNX model only needs `onnxruntime` to run — no PyTorch,
no Ultralytics, no GPU. Deploy that single file to the UNO Q.

Usage
-----
    # Default: yolov8n.pt -> linux/models/yolov8n.onnx + yolov8n_int8.onnx
    python3 quantize.py

    # Custom model / output dir / input size
    python3 quantize.py --model yolov8n.pt --out models/ --imgsz 416

Output
------
    <out>/yolov8n.onnx        FP32 baseline
    <out>/yolov8n_int8.onnx   INT8 dynamic-quantized (deploy this one)

The INT8 model is typically ~40–50 % smaller and 1.5–2× faster on ARM CPUs
with negligible accuracy loss for person detection.

Deploy to the UNO Q
-------------------
    scp linux/models/yolov8n_int8.onnx arduino@uno-q:~/darkmap/
    python3 pipeline.py --source bridge --model ~/darkmap/yolov8n_int8.onnx
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def export_to_onnx(model_path: str, out_dir: str, imgsz: int) -> str:
    """Export a .pt model to ONNX FP32 using Ultralytics.

    Returns the path of the exported .onnx file.
    """
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        sys.exit("[quantize] ERROR: ultralytics is required for export.\n"
                 "  pip install ultralytics")

    print(f"[quantize] Loading {model_path} ...")
    model = YOLO(model_path)

    stem = os.path.splitext(os.path.basename(model_path))[0]
    print(f"[quantize] Exporting to ONNX (imgsz={imgsz}, simplify=True) ...")
    t0 = time.time()
    exported = model.export(
        format="onnx",
        imgsz=imgsz,
        simplify=True,
        opset=12,
        dynamic=False,
    )
    elapsed = time.time() - t0
    print(f"[quantize] Export done in {elapsed:.1f}s  ->  {exported}")

    # Ultralytics writes the .onnx next to the .pt; move it to out_dir.
    dest = os.path.join(out_dir, stem + ".onnx")
    if os.path.abspath(str(exported)) != os.path.abspath(dest):
        shutil.move(str(exported), dest)
    size_mb = os.path.getsize(dest) / 1e6
    print(f"[quantize] FP32 ONNX  {dest}  ({size_mb:.1f} MB)")
    return dest


def quantize_int8(fp32_path: str, int8_path: str) -> str:
    """Dynamic INT8 quantization via ONNX Runtime.

    Weights are quantized to UINT8; activations are quantized dynamically at
    inference time.  No calibration dataset is needed.

    Returns the path of the INT8 model.
    """
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType  # type: ignore
    except ImportError:
        sys.exit("[quantize] ERROR: onnxruntime is required for quantization.\n"
                 "  pip install onnxruntime")

    print(f"[quantize] Quantizing to INT8 (dynamic) ...")
    t0 = time.time()
    quantize_dynamic(
        model_input=fp32_path,
        model_output=int8_path,
        weight_type=QuantType.QUInt8,
    )
    elapsed = time.time() - t0
    fp32_mb = os.path.getsize(fp32_path) / 1e6
    int8_mb = os.path.getsize(int8_path) / 1e6
    ratio = int8_mb / fp32_mb * 100
    print(f"[quantize] Quantization done in {elapsed:.1f}s")
    print(f"[quantize] FP32  {fp32_mb:.1f} MB")
    print(f"[quantize] INT8  {int8_mb:.1f} MB  ({ratio:.0f}% of FP32,  "
          f"{fp32_mb - int8_mb:.1f} MB saved)")
    return int8_path


def verify(fp32_path: str, int8_path: str, imgsz: int) -> None:
    """Quick sanity-check: run a dummy forward pass on both models."""
    try:
        import numpy as np  # type: ignore
        import onnxruntime as ort  # type: ignore
    except ImportError:
        print("[quantize] Skipping verification (numpy/onnxruntime missing).")
        return

    dummy = np.zeros((1, 3, imgsz, imgsz), dtype=np.float32)
    for label, path in [("FP32", fp32_path), ("INT8", int8_path)]:
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        inp_name = sess.get_inputs()[0].name
        t0 = time.time()
        out = sess.run(None, {inp_name: dummy})
        ms = (time.time() - t0) * 1000
        print(f"[quantize] {label} forward pass OK  output={out[0].shape}  "
              f"time={ms:.0f}ms")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Export + INT8 quantize YOLOv8 for edge")
    p.add_argument("--model",  default="yolov8n.pt",
                   help="source .pt model (default: yolov8n.pt)")
    p.add_argument("--out",    default=None,
                   help="output directory (default: <script_dir>/models/)")
    p.add_argument("--imgsz", type=int, default=416,
                   help="inference image size (default: 416 — good for ARM edge)")
    p.add_argument("--skip-export",  action="store_true",
                   help="skip Ultralytics export (use existing FP32 .onnx)")
    p.add_argument("--skip-verify",  action="store_true",
                   help="skip the forward-pass verification")
    args = p.parse_args(argv)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = args.out or os.path.join(script_dir, "models")
    _ensure_dir(out_dir)

    stem = os.path.splitext(os.path.basename(args.model))[0]
    fp32_path = os.path.join(out_dir, stem + ".onnx")
    int8_path = os.path.join(out_dir, stem + "_int8.onnx")

    if args.skip_export:
        if not os.path.exists(fp32_path):
            sys.exit(f"[quantize] --skip-export set but {fp32_path} not found.")
        print(f"[quantize] Reusing existing FP32 model: {fp32_path}")
    else:
        fp32_path = export_to_onnx(args.model, out_dir, args.imgsz)

    quantize_int8(fp32_path, int8_path)

    if not args.skip_verify:
        verify(fp32_path, int8_path, args.imgsz)

    print(f"\n[quantize] Done.")
    print(f"  FP32  {fp32_path}")
    print(f"  INT8  {int8_path}  <- deploy this to the UNO Q")
    print(f"\n  On the UNO Q (onnxruntime only, no ultralytics needed):")
    print(f"  python3 pipeline.py --source bridge --model {int8_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
