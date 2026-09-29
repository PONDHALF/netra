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


def draw_frame(frame: np.ndarray, items: list[dict], font_path: str | None = None) -> np.ndarray:
    """items: [{box, plate, cls, label}] — box/plate เป็น tuple(x1,y1,x2,y2) ในพิกัดของ frame."""
    if not items:
        return frame
    h = frame.shape[0]
    thick = max(2, h // 400)
    size = max(14, h // 42)
    labels = []
    for it in items:
        color = COLORS.get(it["cls"], (200, 200, 200))
        x1, y1, x2, y2 = it["box"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)
        if it.get("plate"):
            px1, py1, px2, py2 = it["plate"]
            cv2.rectangle(frame, (px1, py1), (px2, py2), PLATE_COLOR, thick)
        labels.append((x1, y1, it["label"], color))

    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    font = _font(size, font_path)
    for x1, y1, text, color in labels:
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        tw, th = r - l, b - t
        pad = size // 4
        ty = max(0, y1 - th - 2 * pad)
        d.rectangle([x1, ty, x1 + tw + 2 * pad, ty + th + 2 * pad], fill=(color[2], color[1], color[0]))
        d.text((x1 + pad, ty + pad - t), text, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
