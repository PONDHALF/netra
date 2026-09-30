"""ค่าตั้งต้นของ engine (override ได้ด้วย environment variable)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"

# COCO class id → ประเภทรถ
VEHICLE_CLASSES: dict[int, str] = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def limit_threads() -> int:
    """จำกัด thread ของ PyTorch/OpenCV — ค่าเริ่มต้น min(8, จำนวน core)
    เครื่องที่มี core เยอะ (เช่น 72) ถ้าปล่อยตามค่าเริ่มต้น การประสาน thread จะกินเวลามากกว่างานจริง."""
    n = int(os.getenv("NETRA_THREADS", "0")) or min(8, os.cpu_count() or 8)
    try:
        import torch

        torch.set_num_threads(n)
    except Exception:  # noqa: BLE001
        pass
    try:
        import cv2

        cv2.setNumThreads(n)
    except Exception:  # noqa: BLE001
        pass
    return n


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
    # PlateNet: ตัวอ่านป้ายที่เทรนเอง (training/plate_ocr) — ถ้ามีไฟล์ จะใช้คู่กับ char-OCR
    platenet_model: str = os.getenv("NETRA_PLATENET_MODEL", str(MODELS_DIR / "platenet.pt"))
    # Typhoon OCR 3B ช่วยอ่านจังหวัด/ป้ายที่อ่านไม่ครบ — ใช้แรม ~7.5 GB จึงปิดเป็นค่าเริ่มต้น
    typhoon: bool = os.getenv("NETRA_TYPHOON", "0") == "1"
    # เก็บ Typhoon ไว้ในหน่วยความจำหลังใช้ (ไม่ต้องโหลดใหม่ ~7.5 GB ทุกงาน) — auto = เก็บเมื่อใช้ GPU NVIDIA
    typhoon_keep: str = os.getenv("NETRA_TYPHOON_KEEP", "auto")

    @property
    def keep_typhoon_loaded(self) -> bool:
        if self.typhoon_keep == "auto":
            return self.device.startswith("cuda")
        return self.typhoon_keep == "1"
    device: str = field(default_factory=auto_device)
    imgsz: int = int(os.getenv("NETRA_IMGSZ", "640"))
    # ป้ายในภาพกล้องวงจรปิดเล็กมาก (~30 px ที่ 1080p) — ถ้าย่อทั้งภาพเหลือ 640 จะหาไม่เจอเลย
    plate_imgsz: int = int(os.getenv("NETRA_PLATE_IMGSZ", "1280"))
    # หาป้าย: frame = ทั้งภาพที่ plate_imgsz | crops = เฉพาะในกรอบรถ รวมเป็นภาพเดียว (mosaic) ขนาด plate_crop_imgsz
    # (ภาพเล็กลง ~4 เท่า และรถถูกขยายให้เต็มช่อง ป้ายเล็กจึงใหญ่ขึ้น)
    plate_mode: str = os.getenv("NETRA_PLATE_MODE", "frame")
    plate_crop_imgsz: int = int(os.getenv("NETRA_PLATE_CROP_IMGSZ", "640"))
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
    # EasyOCR (ตัวอ่านสำรอง) ใช้ GPU หรือไม่: auto = ใช้ CPU บนการ์ด NVIDIA เพื่อคืน VRAM ~1–2 GB ให้ Typhoon/กล้อง
    # (ถูกเรียกไม่บ่อยและรันใน thread สรุปผล ไม่กระทบภาพสด), ใช้ GPU บน Mac (MPS)
    ocr_gpu_mode: str = os.getenv("NETRA_OCR_GPU", "auto")

    @property
    def ocr_gpu(self) -> bool:
        if self.ocr_gpu_mode == "auto":
            return not self.device.startswith("cuda")
        return self.ocr_gpu_mode == "1"
    max_output_width: int = 1280
    font_path: str | None = os.getenv("NETRA_FONT")
