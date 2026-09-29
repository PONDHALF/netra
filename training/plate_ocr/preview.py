"""ดูตัวอย่างป้ายจำลองที่ใช้เทรน PlateNet

    python -m training.plate_ocr.preview            # สุ่มใหม่ทุกครั้ง → data/outputs/synth/
    python -m training.plate_ocr.preview --seed 1   # ชุดเดิมซ้ำได้

สร้าง 2 ไฟล์
  clean.jpg     ป้ายก่อนทำให้เสื่อม (เห็นรูปแบบ สี ฟอนต์ กรอบป้าย ชัดๆ)
  training.jpg  ภาพที่โมเดลเห็นจริงตอนเทรน (64×192 หลังบิดมุม/เบลอ/ย่อ/noise) พร้อมเฉลยใต้ภาพ
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.platenet import PROVINCE_CLASSES  # noqa: E402
from training.plate_ocr.synth import _font, add_holder, available_fonts, make_sample, render_plate  # noqa: E402

FONT_DIR = ROOT / "data" / "fonts"
OUT = ROOT / "data" / "outputs" / "synth"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--n", type=int, default=48, help="จำนวนภาพ (หาร 6 ลงตัว)")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    fonts = available_fonts(FONT_DIR)
    OUT.mkdir(parents=True, exist_ok=True)

    # ป้ายก่อนทำให้เสื่อม
    rng = random.Random(seed)
    clean = []
    for i in range(12):
        img = render_plate(rng, fonts)[0]
        if i % 2:
            img = add_holder(rng, img, fonts)
        clean.append(cv2.resize(cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR), (340, 170)))
    rows = [np.hstack([cv2.copyMakeBorder(c, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=(40, 40, 40)) for c in clean[i:i + 4]])
            for i in range(0, 12, 4)]
    cv2.imwrite(str(OUT / "clean.jpg"), np.vstack(rows))

    # ภาพที่โมเดลเห็นจริง + เฉลย
    rng = random.Random(seed + 1)
    np.random.seed(seed % 2**32)
    label_font = _font(fonts[0], 13)
    tiles = []
    for _ in range(args.n):
        s = make_sample(rng, fonts)
        tile = Image.new("RGB", (192, 64 + 20), (30, 30, 30))
        tile.paste(Image.fromarray(s.image), (0, 0))
        ImageDraw.Draw(tile).text((3, 65), f"{s.text}  {PROVINCE_CLASSES[s.province]}", font=label_font, fill=(230, 230, 230))
        tiles.append(cv2.copyMakeBorder(cv2.cvtColor(np.asarray(tile), cv2.COLOR_RGB2BGR), 2, 2, 2, 2,
                                        cv2.BORDER_CONSTANT, value=(60, 60, 60)))
    rows = [np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles) - len(tiles) % 6, 6)]
    cv2.imwrite(str(OUT / "training.jpg"), np.vstack(rows))
    print(f"seed {seed} → {(OUT / 'clean.jpg').relative_to(ROOT)}, {(OUT / 'training.jpg').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
