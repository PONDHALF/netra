"""ตรวจจับรถ (YOLO11s + ByteTrack) และตรวจจับป้าย (YOLO11n เทรนป้ายไทย)."""
from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import locks
from .config import VEHICLE_CLASSES, EngineConfig

log = logging.getLogger("netra.engine")


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def as_int(self) -> tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(self.x2), int(self.y2)


@dataclass
class TrackedVehicle:
    track_id: int
    cls: str
    box: Box
    plate: Box | None = None


def _load_yolo(path: str, fallback_name: str | None = None, imgsz: int | None = None, device: str = "cpu"):
    from ultralytics import YOLO

    from . import trt

    p = Path(path)
    if p.exists():
        # การ์ด NVIDIA: ใช้ TensorRT ถ้าทำได้ (แปลงอัตโนมัติครั้งแรก) — ไม่งั้นใช้ .pt ตามเดิม
        return YOLO(trt.model_path(p, imgsz, device) if imgsz else str(p), task="detect")
    if fallback_name is None:
        return None
    # ครั้งแรก: ให้ Ultralytics ดาวน์โหลดโมเดลมาตรฐาน แล้วย้ายไปเก็บที่ engine/models/
    model = YOLO(fallback_name)
    downloaded = Path(fallback_name)
    if downloaded.exists() and not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(downloaded), p)
    return model


class VehicleTracker:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.model = _load_yolo(cfg.vehicle_model, fallback_name=Path(cfg.vehicle_model).name,
                                imgsz=cfg.imgsz, device=cfg.device)
        self._lock = threading.Lock()
        log.info("vehicle model: %s on %s", Path(self.model.ckpt_path or cfg.vehicle_model).name, cfg.device)

    def reset(self) -> None:
        # ล้างสถานะ tracker ระหว่างวิดีโอ
        predictor = getattr(self.model, "predictor", None)
        if predictor is not None and hasattr(predictor, "trackers"):
            for t in predictor.trackers:
                t.reset()

    def track(self, frame: np.ndarray) -> list[tuple[int, str, Box]]:
        # แปลง tensor → numpy ภายใน lock ด้วย (.cpu() ก็ใช้ GPU)
        with locks.guard(self._lock, exclusive=locks.needs_setup(self.model)):
            res = self._track(frame)
            if res.boxes is None or res.boxes.id is None:
                return []
            xyxy = res.boxes.xyxy.cpu().numpy()
            ids = res.boxes.id.int().cpu().numpy()
            clss = res.boxes.cls.int().cpu().numpy()
            confs = res.boxes.conf.cpu().numpy()
        return [(int(tid), VEHICLE_CLASSES.get(int(c), "car"), Box(x1, y1, x2, y2, float(cf)))
                for (x1, y1, x2, y2), tid, c, cf in zip(xyxy, ids, clss, confs)]

    def _track(self, frame: np.ndarray):
        return self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=list(VEHICLE_CLASSES),
            conf=self.cfg.vehicle_conf,
            imgsz=self.cfg.imgsz,
            device=self.cfg.device,
            verbose=False,
        )[0]


class PlateDetector:
    """ใช้โมเดลป้ายที่เทรนเอง (engine/models/plate.pt) ถ้ามี — ถ้าไม่มีจะคืน None
    แล้ว pipeline จะใช้ text detector ของ EasyOCR หาป้ายในภาพรถแทน."""

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.model = _load_yolo(cfg.plate_model, imgsz=cfg.plate_imgsz, device=cfg.device)
        self._lock = threading.Lock()  # ใช้ร่วมกันระหว่างงานวิดีโอกับกล้องสด — predictor ของ ultralytics ไม่ thread-safe
        if self.model is None:
            log.warning("ไม่พบโมเดลป้าย %s — ใช้โหมดสำรอง (EasyOCR หาข้อความในภาพรถ)", cfg.plate_model)

    @property
    def available(self) -> bool:
        return self.model is not None

    def detect(self, frame: np.ndarray) -> list[Box]:
        if self.model is None:
            return []
        with locks.guard(self._lock, exclusive=locks.needs_setup(self.model)):
            res = self.model.predict(frame, conf=self.cfg.plate_conf, imgsz=self.cfg.plate_imgsz,
                                     device=self.cfg.device, verbose=False)[0]
            if res.boxes is None:
                return []
            xyxy, conf = res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()
        return [Box(*b, float(c)) for b, c in zip(xyxy, conf)]


def assign_plates(vehicles: list[tuple[int, str, Box]], plates: list[Box]) -> list[TrackedVehicle]:
    """จับคู่ป้ายเข้ากับรถ: จุดกึ่งกลางของป้ายต้องอยู่ในกรอบรถ เลือกรถที่เล็กที่สุดที่ครอบป้ายได้."""
    out = [TrackedVehicle(tid, cls, box) for tid, cls, box in vehicles]
    for p in sorted(plates, key=lambda b: -b.conf):
        cx, cy = (p.x1 + p.x2) / 2, (p.y1 + p.y2) / 2
        owners = [v for v in out if v.plate is None and v.box.contains(cx, cy)]
        if owners:
            min(owners, key=lambda v: v.box.area).plate = p
    return out
