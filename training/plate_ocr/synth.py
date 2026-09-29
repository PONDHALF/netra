"""สร้างภาพป้ายทะเบียนไทยจำลอง (synthetic) สำหรับเทรน PlateNet — ไม่ต้องมีข้อมูลจริง

ขั้นตอน: สุ่มเลข/จังหวัดตามกติกาจริง → วาดป้ายความละเอียดสูง (หลายแบบสี/ฟอนต์/รูปแบบ)
→ ทำให้ดูเหมือนภาพจากกล้องจริง: บิดมุม, วางบนพื้นหลัง, แสงเงา, เบลอ, ย่อเหลือเล็กมาก, noise, JPEG, สิ่งสกปรก
ความละเอียดต่ำ (ป้ายกว้าง 25–60 px) ถูกสุ่มบ่อยเป็นพิเศษ เพราะเป็นกรณีที่กล้องริมถนนเจอจริง
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from engine.platenet import INPUT_H, INPUT_W, NO_PROVINCE, PROVINCE_CLASSES
from engine.postprocess.provinces import PROVINCES

LETTERS = [c for c in "กขคฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"]  # ไม่มี ฃ ฅ (เลิกใช้แล้ว)
# จังหวัดที่พบบ่อยในข้อมูลจริง (กทม./ปริมณฑล) ให้โอกาสมากกว่า — ที่เหลือสุ่มเท่ากัน
_PROV_WEIGHTS = [8.0 if p == "กรุงเทพมหานคร" else 2.0 if p in ("นนทบุรี", "ปทุมธานี", "สมุทรปราการ", "ขอนแก่น",
                                                                 "ชลบุรี", "เชียงใหม่", "นครราชสีมา") else 1.0
                 for p in PROVINCES]

# (สัดส่วน, พื้นหลัง RGB, สีตัวอักษร RGB) — ป้ายไทยแบบต่างๆ
STYLES = [
    (0.52, (240, 240, 236), (15, 15, 15)),     # ส่วนบุคคล ขาว/ดำ
    (0.12, (236, 190, 30), (15, 15, 15)),      # แท็กซี่/สาธารณะ เหลือง/ดำ
    (0.09, (240, 240, 236), (20, 110, 50)),    # รถบรรทุกส่วนบุคคล ขาว/เขียว
    (0.05, (240, 240, 236), (25, 60, 150)),    # รถตู้/บัสส่วนบุคคล ขาว/น้ำเงิน
    (0.06, (200, 30, 40), (20, 20, 20)),       # ป้ายแดง
    (0.08, None, (15, 15, 15)),                # ป้ายกราฟิก/ประมูล (พื้นลาย)
    (0.08, (240, 240, 236), (15, 15, 15)),     # (ใช้กับรูปแบบจักรยานยนต์)
]


@dataclass
class Sample:
    image: np.ndarray       # RGB uint8 INPUT_H×INPUT_W
    text: str               # "1กข1234" (ไม่มีช่องว่าง)
    province: int           # ดัชนีใน PROVINCE_CLASSES


def random_plate(rng: random.Random) -> tuple[str, str, str]:
    """คืน (หมวดอักษร, ตัวเลข, จังหวัด) ตามรูปแบบป้ายรถยนต์ไทย."""
    prefix = str(rng.randint(1, 9)) if rng.random() < 0.5 else ""
    letters = "".join(rng.choice(LETTERS) for _ in range(2 if rng.random() < 0.85 else 1))
    n_digits = rng.choices([1, 2, 3, 4], weights=[0.05, 0.15, 0.25, 0.55])[0]
    number = str(rng.randint(10 ** (n_digits - 1) if n_digits > 1 else 1, 10 ** n_digits - 1))
    province = rng.choices(PROVINCES, weights=_PROV_WEIGHTS)[0]
    return prefix + letters, number, province


@lru_cache(maxsize=256)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font_path: str, max_w: float, max_h: float) -> ImageFont.FreeTypeFont:
    lo, hi = 8, 400
    while lo < hi:  # หาขนาดฟอนต์ใหญ่สุดที่ยังพอดี
        mid = (lo + hi + 1) // 2
        l, t, r, b = draw.textbbox((0, 0), text, font=_font(font_path, mid))
        if r - l <= max_w and b - t <= max_h:
            lo = mid
        else:
            hi = mid - 1
    return _font(font_path, lo)


def _text_center(draw, cx, cy, text, font, fill, stretch_y: float = 1.0, img: Image.Image | None = None):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    if stretch_y != 1.0 and img is not None:  # ฟอนต์ป้ายจริงผอมสูง — วาดแยกแล้วยืดแนวตั้ง
        w, h = r - l, b - t
        layer = Image.new("L", (w + 4, h + 4), 0)
        ImageDraw.Draw(layer).text((2 - l, 2 - t), text, font=font, fill=255)
        layer = layer.resize((w + 4, int((h + 4) * stretch_y)), Image.BICUBIC)
        color = Image.new("RGB", layer.size, fill)
        img.paste(color, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)
        return
    draw.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t), text, font=font, fill=fill)


def _graphic_bg(rng: random.Random, w: int, h: int) -> Image.Image:
    """พื้นหลังป้ายกราฟิก: ไล่สีอ่อน + ลายวงกลม/เส้น."""
    a = np.array([rng.randint(170, 255) for _ in range(3)], np.float32)
    b = np.array([rng.randint(170, 255) for _ in range(3)], np.float32)
    t = np.linspace(0, 1, w)[None, :, None]
    arr = (a * (1 - t) + b * t).repeat(h, 0).astype(np.uint8)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for _ in range(rng.randint(2, 8)):
        c = tuple(rng.randint(150, 255) for _ in range(3))
        x, y, r = rng.randint(0, w), rng.randint(0, h), rng.randint(20, h)
        d.ellipse([x - r, y - r, x + r, y + r], outline=c, width=rng.randint(2, 10))
    return img


def render_plate(rng: random.Random, fonts: list[str]) -> tuple[Image.Image, str, str]:
    """วาดป้ายความละเอียดสูง (ยังไม่ทำให้เสื่อม) → (ภาพ, ข้อความ, จังหวัด)."""
    top, number, province = random_plate(rng)
    style_i = rng.choices(range(len(STYLES)), weights=[s[0] for s in STYLES])[0]
    _, bg, fg = STYLES[style_i]
    moto = style_i == len(STYLES) - 1
    font = rng.choice(fonts)
    stretch = rng.uniform(1.0, 1.35)

    if moto:  # จักรยานยนต์: 3 บรรทัด หมวด / จังหวัด / เลข
        W, H = 460, 320
        top = (str(rng.randint(1, 9)) if rng.random() < 0.7 else "") + "".join(rng.choice(LETTERS) for _ in range(2))
        number = str(rng.randint(1, 999))
    else:
        W, H = 680, 300
    img = _graphic_bg(rng, W, H) if bg is None else Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    bw = rng.randint(5, 12)
    d.rounded_rectangle([bw // 2, bw // 2, W - bw // 2, H - bw // 2], radius=rng.randint(8, 24), outline=fg, width=bw)

    if moto:
        f1 = _fit(d, top, font, W * 0.7, H * 0.26)
        _text_center(d, W / 2, H * 0.2, top, f1, fg)
        fp = _fit(d, province, font, W * 0.8, H * 0.16)
        _text_center(d, W / 2, H * 0.43, province, fp, fg)
        f3 = _fit(d, number, font, W * 0.8, H * 0.32 / stretch)
        _text_center(d, W / 2, H * 0.72, number, f3, fg, stretch, img)
    else:
        line1 = f"{top} {number}" if rng.random() < 0.85 else f"{top}  {number}"
        f1 = _fit(d, line1, font, W * rng.uniform(0.8, 0.9), H * 0.5 / stretch)
        _text_center(d, W / 2, H * rng.uniform(0.33, 0.38), line1, f1, fg, stretch, img)
        fp = _fit(d, province, font, W * rng.uniform(0.6, 0.82), H * 0.2)
        _text_center(d, W / 2, H * rng.uniform(0.77, 0.81), province, fp, fg)
    return img, top + number, province


# ------------------------------------------------------------------ ทำให้เหมือนภาพจากกล้องจริง
def _perspective(rng, img: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """วางป้ายบนพื้นหลัง (เหมือนภาพที่ตัดจากตัวตรวจจับ + ขอบเผื่อ) แล้วบิดมุมเล็กน้อย."""
    h, w = img.shape[:2]
    pad_x, pad_y = w * rng.uniform(0.0, 0.14), h * rng.uniform(0.0, 0.2)
    ow, oh = int(w + 2 * pad_x), int(h + 2 * pad_y)
    j = lambda s: rng.uniform(-s, s)  # noqa: E731
    k = 0.07
    dst = np.float32([[pad_x + j(w * k), pad_y + j(h * k)], [pad_x + w + j(w * k), pad_y + j(h * k)],
                      [pad_x + w + j(w * k), pad_y + h + j(h * k)], [pad_x + j(w * k), pad_y + h + j(h * k)]])
    ang = math.radians(rng.uniform(-6, 6))
    c = dst.mean(0)
    rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]], np.float32)
    dst = (dst - c) @ rot.T + c
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, dst)
    bg = cv2.resize(bg, (ow, oh))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (ow, oh))
    warped = cv2.warpPerspective(img, M, (ow, oh), flags=cv2.INTER_LINEAR)
    m = (mask.astype(np.float32) / 255.0)[..., None]
    return (warped * m + bg * (1 - m)).astype(np.uint8)


def _background(rng, h: int, w: int) -> np.ndarray:
    """พื้นหลังรอบป้าย: สีกันชนรถ + ไล่แสง + noise."""
    base = np.array(rng.choice([(20, 20, 20), (200, 200, 200), (120, 120, 125), (150, 30, 30), (240, 240, 240),
                                (40, 60, 110), (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))]),
                    np.float32)
    g = np.linspace(rng.uniform(0.6, 1.0), rng.uniform(0.6, 1.2), h)[:, None, None]
    arr = np.clip(base * g + np.random.normal(0, 12, (h, w, 3)), 0, 255)
    return arr.astype(np.uint8)


def degrade(rng: random.Random, plate: Image.Image) -> np.ndarray:
    img = np.asarray(plate)  # RGB
    h, w = img.shape[:2]
    img = _perspective(rng, img, _background(rng, h, w))

    # สิ่งสกปรก / น็อตยึดป้าย / เส้นขีด
    if rng.random() < 0.35:
        for _ in range(rng.randint(1, 4)):
            c = tuple(int(v) for v in np.random.randint(0, 120, 3))
            x, y = rng.randint(0, img.shape[1]), rng.randint(0, img.shape[0])
            cv2.circle(img, (x, y), rng.randint(3, 14), c, -1)

    # แสง: ความสว่าง/contrast/gamma + เงาไล่ระดับ
    f = img.astype(np.float32)
    f = f * rng.uniform(0.55, 1.35) + rng.uniform(-35, 35)
    if rng.random() < 0.4:
        sh = np.linspace(rng.uniform(0.4, 1.0), rng.uniform(0.7, 1.1), f.shape[1])[None, :, None]
        f = f * sh
    f = 255 * (np.clip(f, 0, 255) / 255) ** rng.uniform(0.7, 1.4)
    img = np.clip(f, 0, 255).astype(np.uint8)

    # ความละเอียดเป้าหมายของป้าย (กว้าง 22–220 px เน้นช่วงเล็ก) — สุ่มก่อน เพื่อคุมไม่ให้ทั้งเล็กและเบลอหนักจนคนยังอ่านไม่ได้
    target_w = int(math.exp(rng.uniform(math.log(22), math.log(220))))
    heavy_ok = target_w >= 60

    # เบลอ: Gaussian หรือเบลอจากการเคลื่อนที่ (ป้ายเล็กมากเบลอได้แค่เล็กน้อย เพราะการย่อก็เบลออยู่แล้ว)
    r = rng.random()
    if r < 0.35:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.5, 2.5 if heavy_ok else 1.0))
    elif r < 0.6:
        k = rng.choice([5, 7, 9, 13] if heavy_ok else [3, 5])
        ker = np.zeros((k, k), np.float32)
        ker[k // 2, :] = 1.0 / k
        M = cv2.getRotationMatrix2D((k / 2, k / 2), rng.uniform(-30, 30), 1)
        ker = cv2.warpAffine(ker, M, (k, k))
        img = cv2.filter2D(img, -1, ker / max(ker.sum(), 1e-6))

    # ความละเอียดต่ำ: ย่อป้ายตามขนาดเป้าหมายแล้วขยายกลับ — กรณีหลักของกล้องริมถนน
    s = target_w / img.shape[1]
    small = cv2.resize(img, (max(8, target_w), max(4, int(img.shape[0] * s))), interpolation=cv2.INTER_AREA)
    if rng.random() < 0.8:
        q = rng.randint(25 if target_w < 40 else 15, 90)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
        small = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    img = cv2.resize(small, (INPUT_W, INPUT_H), interpolation=rng.choice([cv2.INTER_LINEAR, cv2.INTER_CUBIC]))

    if rng.random() < 0.6:  # noise ของเซนเซอร์
        img = np.clip(img.astype(np.float32) + np.random.normal(0, rng.uniform(2, 12), img.shape), 0, 255).astype(np.uint8)
    if rng.random() < 0.2:  # กล้องกลางคืน/IR ขาวดำ
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        img = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
    return img


def make_sample(rng: random.Random, fonts: list[str]) -> Sample:
    plate, text, province = render_plate(rng, fonts)
    img = degrade(rng, plate)
    # ป้ายถูกตัดขอบล่างจนไม่เห็นจังหวัด (ตัวตรวจจับตัดพลาด) — สอนให้ตอบ "ไม่เห็น"
    prov_idx = PROVINCE_CLASSES.index(province)
    if rng.random() < 0.05:
        cut = int(INPUT_H * rng.uniform(0.62, 0.72))
        img = cv2.resize(img[:cut], (INPUT_W, INPUT_H))
        prov_idx = NO_PROVINCE
    return Sample(img, text, prov_idx)


def available_fonts(font_dir: Path) -> list[str]:
    fonts = sorted(str(p) for p in font_dir.glob("*.ttf"))
    if not fonts:
        raise SystemExit(f"ไม่พบฟอนต์ใน {font_dir} — รัน: python -m training.plate_ocr.fonts")
    return fonts
