"""ดาวน์โหลดฟอนต์ไทย (SIL Open Font License) จาก Google Fonts สำหรับสร้างป้ายจำลอง

    python -m training.plate_ocr.fonts      → data/fonts/*.ttf

ตรึง commit ของ google/fonts ไว้ ให้ภาพจำลองเหมือนเดิมทุกเครื่อง
เลือกฟอนต์หนา/ผอมสูงที่ใกล้เคียงฟอนต์ป้ายทะเบียนจริง + ฟอนต์ทั่วไปเพื่อความหลากหลาย
"""
from __future__ import annotations

import socket
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "data" / "fonts"
COMMIT = "23e54b51ddffbc7713c583748e3bd86f62b1fa4a"
FONTS = [
    "kanit/Kanit-Medium.ttf", "kanit/Kanit-SemiBold.ttf",
    "prompt/Prompt-Medium.ttf", "prompt/Prompt-SemiBold.ttf",
    "chakrapetch/ChakraPetch-Medium.ttf", "chakrapetch/ChakraPetch-SemiBold.ttf",
    "baijamjuree/BaiJamjuree-Medium.ttf", "k2d/K2D-Medium.ttf", "mitr/Mitr-Medium.ttf",
    "sarabun/Sarabun-Medium.ttf", "krub/Krub-Medium.ttf", "niramit/Niramit-Medium.ttf",
]


def main() -> None:
    socket.setdefaulttimeout(60)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for f in FONTS:
        dest = FONT_DIR / Path(f).name
        if dest.exists():
            continue
        url = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/{f}"
        print(f"↓ {dest.name}")
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)
    n = len(list(FONT_DIR.glob("*.ttf")))
    print(f"✓ ฟอนต์ {n} ไฟล์ใน {FONT_DIR.relative_to(ROOT)}")
    sys.exit(0 if n else 1)


if __name__ == "__main__":
    main()
