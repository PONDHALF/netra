"""TensorRT สำหรับโมเดล YOLO บนการ์ด NVIDIA — แปลงอัตโนมัติครั้งแรก แล้วเก็บไว้ใน cache

ทำไม: บนเครื่อง CPU ช้า (เช่น Xeon E5 v4) PyTorch ใช้เวลาสั่งงาน GPU ทีละ kernel นานกว่าที่ GPU คำนวณจริง
YOLO11s @640 บน RTX 3060 ใช้ ~22 ms แบบ PyTorch ทั้งที่ GPU ทำได้ ~5 ms — TensorRT รวมทั้งโมเดลเป็นก้อนเดียว
จึงแทบไม่เสียเวลาฝั่ง CPU

- เปิด/ปิด: NETRA_TRT = auto (ค่าเริ่มต้น: ใช้เมื่อเป็น cuda และติดตั้ง tensorrt) | 1 | 0
- ไฟล์ .engine ผูกกับรุ่นการ์ดจอ + เวอร์ชัน TensorRT จึงตั้งชื่อตามนั้น แปลงใหม่เองเมื่อเปลี่ยน
- แปลงครั้งแรกใช้ ~1–5 นาทีต่อโมเดล (ตอนเริ่มระบบ)
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from pathlib import Path

log = logging.getLogger("netra.engine")
_export_lock = threading.Lock()


def _trt_version() -> str | None:
    try:
        import tensorrt

        return tensorrt.__version__
    except Exception:  # noqa: BLE001
        return None


def enabled(device: str) -> bool:
    mode = os.getenv("NETRA_TRT", "auto")
    if mode == "0" or not device.startswith("cuda"):
        return False
    if _trt_version() is None:
        if mode == "1":
            log.warning("NETRA_TRT=1 แต่ไม่ได้ติดตั้ง tensorrt — ใช้ PyTorch แทน")
        return False
    return True


def cache_dir() -> Path:
    if os.getenv("NETRA_TRT_CACHE"):
        return Path(os.environ["NETRA_TRT_CACHE"])
    if os.getenv("HF_HOME"):  # ใน Docker: /cache/huggingface → /cache/trt (volume เดียวกัน)
        return Path(os.environ["HF_HOME"]).parent / "trt"
    return Path.home() / ".cache" / "netra-trt"


def engine_path(pt: Path, imgsz: int, device: str) -> Path:
    import torch

    idx = int(device.split(":")[1]) if ":" in device else 0
    gpu = re.sub(r"[^A-Za-z0-9]+", "", torch.cuda.get_device_name(idx))
    return cache_dir() / f"{pt.stem}-{imgsz}-fp16-{gpu}-trt{_trt_version()}.engine"


def model_path(pt: str | Path, imgsz: int, device: str) -> str:
    """คืน path ของโมเดลที่ควรโหลด: .engine (แปลงให้ถ้ายังไม่มี) หรือ .pt เดิมถ้าใช้ TensorRT ไม่ได้."""
    pt = Path(pt)
    if not pt.exists() or not enabled(device):
        return str(pt)
    target = engine_path(pt, imgsz, device)
    if target.exists():
        return str(target)
    with _export_lock:
        if target.exists():
            return str(target)
        try:
            from ultralytics import YOLO

            log.info("แปลง %s เป็น TensorRT (imgsz=%d, fp16) ครั้งแรก — รอสักครู่…", pt.name, imgsz)
            idx = int(device.split(":")[1]) if ":" in device else 0
            out = YOLO(str(pt)).export(format="engine", imgsz=imgsz, half=True, device=idx, batch=1,
                                       dynamic=False, simplify=True, workspace=4, verbose=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(out), target)
            onnx = pt.with_suffix(".onnx")  # ไฟล์ชั่วคราวจากการแปลง
            onnx.unlink(missing_ok=True)
            log.info("TensorRT พร้อม: %s", target.name)
            return str(target)
        except Exception as e:  # noqa: BLE001
            log.warning("แปลง %s เป็น TensorRT ไม่สำเร็จ (%s) — ใช้ PyTorch แทน", pt.name, e)
            return str(pt)
