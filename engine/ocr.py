"""อ่านป้ายทะเบียน

- ตัวหลัก: โมเดลอ่านรายตัวอักษร (engine/models/plate_ocr.pt) — แม่นและเร็วกว่า EasyOCR มากบนป้ายไทย
- ตัวสำรอง: EasyOCR (ภาษาไทย) + ปรับภาพ — ใช้เมื่อตัวหลักอ่านได้ไม่ครบ หรือยังไม่มีโมเดล
"""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

from pathlib import Path

from .postprocess import OcrToken, PlateReading, parse_tokens
from . import locks
from .postprocess import plate_chars

log = logging.getLogger("netra.engine")

_THAI_CHARS = "".join(chr(c) for c in range(0x0E01, 0x0E4F))
ALLOWLIST = _THAI_CHARS + "0123456789 "


def sharpness(img: np.ndarray) -> float:
    if img is None or img.size == 0:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def enhance_plate(img: np.ndarray, target_h: int = 160) -> np.ndarray:
    """ขยายภาพป้าย แปลงเป็นขาวดำ และเพิ่ม contrast (CLAHE)."""
    h = img.shape[0]
    if h < target_h:
        scale = target_h / max(h, 1)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
    gray = cv2.bilateralFilter(gray, 5, 50, 50)
    return gray


class CharPlateOCR:
    """โมเดล YOLO ที่ตรวจจับตัวอักษรแต่ละตัวบนป้าย แล้วประกอบเป็นเลขทะเบียน."""

    def __init__(self, path: str, device: str, conf: float = 0.25, imgsz: int = 640):
        from ultralytics import YOLO

        self.model = YOLO(path)
        self.device, self.conf, self.imgsz = device, conf, imgsz
        self._lock = threading.Lock()

    def read(self, img: np.ndarray) -> PlateReading:
        with locks.guard(self._lock):
            res = self.model.predict(img, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)[0]
            boxes, cls, conf = res.boxes.xyxy.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()
        names = self.model.names
        dets = [(names[int(c)], float(cf), tuple(b)) for b, c, cf in zip(boxes, cls, conf)]
        return plate_chars.decode(dets)


class PlateReader:
    def __init__(self, device: str = "cpu", use_gpu: bool = True, char_model: str | None = None):
        import easyocr

        self._easy_lock = threading.Lock()

        self.char: CharPlateOCR | None = None
        if char_model and Path(char_model).exists():
            self.char = CharPlateOCR(char_model, device)
        else:
            log.warning("ไม่พบโมเดลอ่านป้าย %s — ใช้ EasyOCR อย่างเดียว (รัน python -m engine.fetch_models)", char_model)

        gpu: bool | str = False
        if use_gpu and device.startswith("cuda"):
            gpu = True
        elif use_gpu and device == "mps":
            gpu = "mps"
        try:
            self.reader = easyocr.Reader(["th", "en"], gpu=gpu, verbose=False)
        except Exception as e:  # บางเวอร์ชันไม่รองรับ mps
            log.warning("EasyOCR GPU (%s) ใช้ไม่ได้: %s — ใช้ CPU แทน", gpu, e)
            self.reader = easyocr.Reader(["th", "en"], gpu=False, verbose=False)

    def _tokens(self, img: np.ndarray, min_conf: float = 0.05) -> list[tuple[OcrToken, tuple[int, int, int, int]]]:
        with locks.guard(self._easy_lock):
            results = self.reader.readtext(img, allowlist=ALLOWLIST, paragraph=False, decoder="beamsearch",
                                           text_threshold=0.5, low_text=0.3, mag_ratio=1.5)
        out = []
        for pts, text, conf in results:
            text = text.strip()
            if not text or conf < min_conf:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            box = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            out.append((OcrToken(text, float(conf), y=(box[1] + box[3]) / 2, x=(box[0] + box[2]) / 2,
                                 h=box[3] - box[1]), box))
        return out

    def read_plate(self, plate_img: np.ndarray) -> PlateReading:
        """อ่านจากภาพป้ายที่ตัดมาแล้ว: โมเดลรายตัวอักษรก่อน ส่วนที่ขาดให้ EasyOCR เติม."""
        if plate_img is None or plate_img.size == 0:
            return PlateReading()
        if self.char is None:
            r = self.read_plate_easyocr(plate_img)
            r.extras["source"] = "easyocr"
            return r
        r = self.char.read(plate_img)
        if r.valid and r.province:
            return r
        e = self.read_plate_easyocr(plate_img)
        if not r.valid and e.valid:
            r.text, r.conf, r.valid = e.text, e.conf, True
            r.extras["source"] = "easyocr"
        elif not r.text and e.text:
            r.text, r.conf = e.text, e.conf
        if not r.province and e.province:
            r.province = e.province
            r.extras["province_source"] = "easyocr"
        r.raw = f"{r.raw} / easyocr: {e.raw}" if e.raw else r.raw
        return r

    def read_plate_easyocr(self, plate_img: np.ndarray) -> PlateReading:
        img = enhance_plate(plate_img)
        return parse_tokens([t for t, _ in self._tokens(img)])

    def find_and_read(self, car_img: np.ndarray) -> tuple[PlateReading, tuple[int, int, int, int] | None]:
        """โหมดสำรอง: ค้นหาข้อความคล้ายป้ายในครึ่งล่างของภาพรถ.
        คืน (ผลอ่าน, กรอบป้ายในพิกัดของ car_img)."""
        if car_img is None or car_img.size == 0:
            return PlateReading(), None
        h, w = car_img.shape[:2]
        y0 = int(h * 0.35)
        roi = car_img[y0:]
        scale = 1.0
        if roi.shape[1] < 480:
            scale = 480 / max(roi.shape[1], 1)
            roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        tokens = self._tokens(roi, min_conf=0.1)
        if not tokens:
            return PlateReading(), None
        reading = parse_tokens([t for t, _ in tokens])
        if not reading.text:
            return reading, None
        # กรอบป้าย = กรอบของ token ที่อยู่ใกล้ token หลัก (มีตัวเลข) ที่สุด
        main = max((tb for tb in tokens if any(c.isdigit() for c in tb[0].text)), key=lambda tb: tb[0].conf,
                   default=tokens[0])
        mx1, my1, mx2, my2 = main[1]
        mh = my2 - my1
        near = [b for t, b in tokens if abs(t.y - main[0].y) < mh * 2.5 and abs(t.x - main[0].x) < (mx2 - mx1) * 1.2]
        x1 = min(b[0] for b in near); y1 = min(b[1] for b in near)
        x2 = max(b[2] for b in near); y2 = max(b[3] for b in near)
        pad = int(mh * 0.4)
        box = (int(max(0, x1 - pad) / scale), int(max(0, y1 - pad) / scale) + y0,
               int(min(roi.shape[1], x2 + pad) / scale), int(min(roi.shape[0], y2 + pad) / scale) + y0)
        return reading, box
