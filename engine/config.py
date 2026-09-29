"""ค่าตั้งต้นของ engine (override ได้ด้วย environment variable)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"

# COCO class id → ประเภทรถ
VEHICLE_CLASSES: dict[int, str] = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def auto_device() -> str:
    forced = os.getenv("NETRA_DEVICE")
    if forced:
        return forced
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda:0"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


@dataclass
class EngineConfig:
    vehicle_model: str = os.getenv("NETRA_VEHICLE_MODEL", str(MODELS_DIR / "yolo11s.pt"))
    plate_model: str = os.getenv("NETRA_PLATE_MODEL", str(MODELS_DIR / "plate.pt"))
    plate_ocr_model: str = os.getenv("NETRA_PLATE_OCR_MODEL", str(MODELS_DIR / "plate_ocr.pt"))
    # Typhoon OCR 3B ช่วยอ่านจังหวัด/ป้ายที่อ่านไม่ครบ — ใช้แรม ~7.5 GB จึงปิดเป็นค่าเริ่มต้น
    typhoon: bool = os.getenv("NETRA_TYPHOON", "0") == "1"
    device: str = field(default_factory=auto_device)
    imgsz: int = int(os.getenv("NETRA_IMGSZ", "640"))
    # ป้ายในภาพกล้องวงจรปิดเล็กมาก (~30 px ที่ 1080p) — ถ้าย่อทั้งภาพเหลือ 640 จะหาไม่เจอเลย
    plate_imgsz: int = int(os.getenv("NETRA_PLATE_IMGSZ", "1280"))
    vehicle_conf: float = 0.35
    plate_conf: float = 0.30
    # ประมวลผลทุกๆ N เฟรม (0 = อัตโนมัติ ให้ได้ ~15 เฟรม/วินาทีของวิดีโอ)
    frame_stride: int = int(os.getenv("NETRA_FRAME_STRIDE", "0"))
    target_fps: float = 15.0
    # รถหายจากภาพกี่วินาทีจึงถือว่าออกจากภาพแล้ว
    lost_seconds: float = 2.0
    min_track_hits: int = 5           # ต้องเห็นอย่างน้อยกี่เฟรมที่ประมวลผล (~0.3 วินาที) — ตัดเศษ track ที่ขาดตอน
    # ข้ามรถที่ไม่เคยใหญ่เกินสัดส่วนนี้ของความกว้างภาพ (รถไกลๆ ที่ไม่มีทางอ่านป้ายได้)
    min_vehicle_frac: float = float(os.getenv("NETRA_MIN_VEHICLE_FRAC", "0.06"))
    top_k: int = 3                    # จำนวนเฟรมที่ดีที่สุดที่นำไป OCR แล้ว vote
    dedup_seconds: float = 10.0       # ป้ายเดียวกันซ้ำภายในกี่วินาทีให้ถือว่าเป็นคันเดิม
    ocr_gpu: bool = os.getenv("NETRA_OCR_GPU", "auto") != "0"
    max_output_width: int = 1280
    font_path: str | None = os.getenv("NETRA_FONT")
