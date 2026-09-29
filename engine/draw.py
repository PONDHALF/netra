"""วาดกรอบรถ/ป้าย และข้อความภาษาไทยลงบนเฟรม."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    # ต้องมีทั้งอักษรไทยและตัวเลขอารบิก (ThonburiUI ไม่มีตัวเลข)
    "/System/Library/Fonts/Supplemental/Krungthep.ttf",
    "/System/Library/Fonts/Supplemental/Sathu.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/tlwg/Garuda-Bold.ttf",
    "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
]

COLORS = {  # BGR
    "car": (241, 163, 56),
    "motorcycle": (94, 197, 34),
    "bus": (11, 158, 245),
    "truck": (246, 92, 139),
}
PLATE_COLOR = (0, 230, 255)
TYPE_TH = {"car": "รถยนต์", "motorcycle": "จยย.", "bus": "รถบัส", "truck": "รถบรรทุก"}


@lru_cache(maxsize=8)
def _font(size: int, path: str | None):
    for p in ([path] if path else []) + FONT_CANDIDATES:
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


@lru_cache(maxsize=1024)
def _label_patch(text: str, size: int, color: tuple[int, int, int], font_path: str | None) -> np.ndarray:
    """ภาพป้ายข้อความ (BGR) สร้างครั้งเดียวต่อข้อความ — ไม่ต้องแปลงทั้งเฟรมเป็น PIL ทุกเฟรม
    (วาดภาษาไทยต้องใช้ PIL; เดิมใช้ ~26 ms/เฟรมบน CPU ช้า เหลือ <1 ms เมื่อใช้ cache)."""
    font = _font(size, font_path)
    l, t, r, b = font.getbbox(text)
    pad = size // 4
    w, h = (r - l) + 2 * pad, (b - t) + 2 * pad
    img = Image.new("RGB", (max(w, 1), max(h, 1)), (color[2], color[1], color[0]))
    ImageDraw.Draw(img).text((pad - l, pad - t), text, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def draw_frame(frame: np.ndarray, items: list[dict], font_path: str | None = None) -> np.ndarray:
    """items: [{box, plate, cls, label}] — box/plate เป็น tuple(x1,y1,x2,y2) ในพิกัดของ frame (วาดทับ frame เดิม)."""
    if not items:
        return frame
    H, W = frame.shape[:2]
    thick = max(2, H // 400)
    size = max(14, H // 42)
    for it in items:
        color = COLORS.get(it["cls"], (200, 200, 200))
        x1, y1, x2, y2 = it["box"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)
        if it.get("plate"):
            px1, py1, px2, py2 = it["plate"]
            cv2.rectangle(frame, (px1, py1), (px2, py2), PLATE_COLOR, thick)
        if not it.get("label"):
            continue
        patch = _label_patch(it["label"], size, color, font_path)
        ph, pw = patch.shape[:2]
        ty, tx = max(0, y1 - ph), max(0, min(x1, W - 1))
        ph, pw = min(ph, H - ty), min(pw, W - tx)
        if ph > 0 and pw > 0:
            frame[ty:ty + ph, tx:tx + pw] = patch[:ph, :pw]
    return frame
