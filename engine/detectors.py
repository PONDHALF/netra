"""ตรวจจับรถ (YOLO11s + ByteTrack) และตรวจจับป้าย (YOLO11n เทรนป้ายไทย)."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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


def _load_yolo(path: str, fallback_name: str | None = None):
    from ultralytics import YOLO

    p = Path(path)
    if p.exists():
        return YOLO(str(p))
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
        self.model = _load_yolo(cfg.vehicle_model, fallback_name=Path(cfg.vehicle_model).name)
        log.info("vehicle model: %s on %s", cfg.vehicle_model, cfg.device)

    def reset(self) -> None:
        # ล้างสถานะ tracker ระหว่างวิดีโอ
        predictor = getattr(self.model, "predictor", None)
        if predictor is not None and hasattr(predictor, "trackers"):
            for t in predictor.trackers:
                t.reset()

    def track(self, frame: np.ndarray) -> list[tuple[int, str, Box]]:
        res = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=list(VEHICLE_CLASSES),
            conf=self.cfg.vehicle_conf,
            imgsz=self.cfg.imgsz,
            device=self.cfg.device,
            verbose=False,
        )[0]
        out: list[tuple[int, str, Box]] = []
        if res.boxes is None or res.boxes.id is None:
            return out
        xyxy = res.boxes.xyxy.cpu().numpy()
        ids = res.boxes.id.int().cpu().numpy()
        clss = res.boxes.cls.int().cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        for (x1, y1, x2, y2), tid, c, cf in zip(xyxy, ids, clss, confs):
            out.append((int(tid), VEHICLE_CLASSES.get(int(c), "car"), Box(x1, y1, x2, y2, float(cf))))
        return out


class PlateDetector:
    """ใช้โมเดลป้ายที่เทรนเอง (engine/models/plate.pt) ถ้ามี — ถ้าไม่มีจะคืน None
    แล้ว pipeline จะใช้ text detector ของ EasyOCR หาป้ายในภาพรถแทน."""

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.model = _load_yolo(cfg.plate_model)
        if self.model is None:
            log.warning("ไม่พบโมเดลป้าย %s — ใช้โหมดสำรอง (EasyOCR หาข้อความในภาพรถ)", cfg.plate_model)

    @property
    def available(self) -> bool:
        return self.model is not None

    def detect(self, frame: np.ndarray) -> list[Box]:
        if self.model is None:
            return []
        res = self.model.predict(frame, conf=self.cfg.plate_conf, imgsz=self.cfg.plate_imgsz,
                                 device=self.cfg.device, verbose=False)[0]
        if res.boxes is None:
            return []
        return [Box(*b, float(c)) for b, c in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy())]


def assign_plates(vehicles: list[tuple[int, str, Box]], plates: list[Box]) -> list[TrackedVehicle]:
    """จับคู่ป้ายเข้ากับรถ: จุดกึ่งกลางของป้ายต้องอยู่ในกรอบรถ เลือกรถที่เล็กที่สุดที่ครอบป้ายได้."""
    out = [TrackedVehicle(tid, cls, box) for tid, cls, box in vehicles]
    for p in sorted(plates, key=lambda b: -b.conf):
        cx, cy = (p.x1 + p.x2) / 2, (p.y1 + p.y2) / 2
        owners = [v for v in out if v.plate is None and v.box.contains(cx, cy)]
        if owners:
            min(owners, key=lambda v: v.box.area).plate = p
    return out
