"""แปลง dataset ป้ายไทยแบบ "กรอบรายตัวอักษร" (YOLO, จาก Roboflow) เป็นชุดป้ายจริงพร้อมเฉลย สำหรับเทรน/วัดผล PlateNet

    python -m training.plate_ocr.chardata "data/datasets/Thai License Plate Character Recognition"
    python -m training.plate_ocr.chardata data/datasets/thai-license-plate-character-detect --digits-from A45

ภาพใน dataset เหล่านี้คือภาพป้ายที่ตัดแล้ว (ย่อเป็น 640×640) — กรอบแต่ละตัวอักษรบอกเฉลยเลขทะเบียนได้ตรงๆ
  - ตัวเลข "0"–"9" หรือรหัส A01–A44 (= ก–ฮ ตามลำดับ) — บาง dataset ใช้ A45–A54 แทนเลข 0–9 (--digits-from A45)
  - รหัสจังหวัด 3 ตัวอักษร (BKK, KKN, …)
เรียงตัวอักษรตามบรรทัด (บน→ล่าง) แล้วซ้าย→ขวา → "1กข1234"; ป้ายรถบรรทุก/บัสสีเหลือง (ไม่มีหมวดอักษร) → "706843"

ผลลัพธ์: data/datasets/real-plates/<ชื่อ>/labels.csv (status=human, split ตามแฮชของเลขทะเบียน: test ~12%
         — ป้ายเลขเดียวกันอยู่ฝั่งเดียวกันเสมอ ทุก dataset)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.postprocess.plate_chars import PROVINCE_CODES, THAI_ALPHABET  # noqa: E402
from training.plate_ocr.realdata import FIELDS, OUT_ROOT  # noqa: E402

# รหัสจังหวัดที่ไม่มีในโมเดล char-OCR เดิม — ตรวจกับภาพจริงแล้ว (ดู --audit)
EXTRA_PROVINCES = {"NRT": "นครศรีธรรมราช", "NWT": "นราธิวาส", "STN": "สตูล"}


def load_names(ds: Path) -> list[str]:
    import yaml

    n = yaml.safe_load(open(ds / "data.yaml", encoding="utf-8"))["names"]
    return list(n.values()) if isinstance(n, dict) else list(n)


def class_to_token(name: str, digits_from: int | None) -> tuple[str, str] | None:
    """คืน ("char", ตัวอักษร) หรือ ("prov", ชื่อจังหวัด) หรือ None ถ้าไม่รู้จัก."""
    if name.isdigit() and len(name) == 1:
        return "char", name
    m = re.fullmatch(r"A(\d\d)", name)
    if m:
        k = int(m.group(1))
        if digits_from and digits_from <= k < digits_from + 10:
            return "char", str(k - digits_from)
        if 1 <= k <= 44:
            return "char", THAI_ALPHABET[k - 1]
        return None
    prov = PROVINCE_CODES.get(name) or EXTRA_PROVINCES.get(name)
    return ("prov", prov) if prov else None


def read_label(path: Path, names: list[str], digits_from: int | None) -> tuple[str, str, bool]:
    """คืน (เลขทะเบียนไม่มีช่องว่าง, จังหวัด, อ่านได้ครบหรือไม่)."""
    chars, provs, ok = [], [], True
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        c, x, y, w, h = int(parts[0]), *map(float, parts[1:5])
        tok = class_to_token(names[c], digits_from) if c < len(names) else None
        if tok is None:
            ok = False
            continue
        (chars if tok[0] == "char" else provs).append((tok[1], x, y, h))
    if not chars:
        return "", "", False
    # ตัดตัวอักษรเล็กผิดปกติ: ป้ายรถบรรทุก/บัสเหลืองมีบรรทัด "THAILAND 62" (รหัสภาค) ตัวเล็กอยู่ด้านบน
    # ไม่ใช่ส่วนของเลขทะเบียน — ถ้าไม่ตัดจะได้ "62706843" แทน "706843"
    hs = sorted(t[3] for t in chars)
    med = hs[len(hs) // 2]
    chars = [t for t in chars if t[3] >= med * 0.6]
    # จัดบรรทัด: y ใกล้กัน (ต่างไม่เกินครึ่งความสูงตัวอักษร) = บรรทัดเดียวกัน
    chars.sort(key=lambda t: t[2])
    lines: list[list] = []
    for t in chars:
        if lines and abs(t[2] - sum(u[2] for u in lines[-1]) / len(lines[-1])) < max(t[3], lines[-1][0][3]) * 0.5:
            lines[-1].append(t)
        else:
            lines.append([t])
    text = "".join(t[0] for ln in lines for t in sorted(ln, key=lambda u: u[1]))
    province = Counter(p[0] for p in provs).most_common(1)[0][0] if provs else ""
    return text, province, ok


def convert(ds: Path, digits_from: int | None, exclude: set[str]) -> None:
    import cv2

    names = load_names(ds)
    out = OUT_ROOT / ds.name.lower().replace(" ", "-")
    (out / "crops").mkdir(parents=True, exist_ok=True)
    rows, skipped = [], Counter()
    for split_dir in ("train", "valid", "test"):
        for img in sorted((ds / split_dir / "images").glob("*")):
            lab = ds / split_dir / "labels" / (img.stem + ".txt")
            if not lab.exists():
                skipped["no label"] += 1
                continue
            text, province, ok = read_label(lab, names, digits_from)
            valid = bool(re.fullmatch(r"\d?[ก-ฮ]{1,3}\d{1,4}", text) or re.fullmatch(r"\d{2}\d{4}", text))
            if not ok or not valid:
                skipped["unknown class" if not ok else "bad format"] += 1
                continue
            if text in exclude:  # ป้ายเดียวกับชุดทดสอบอิสระ → ไม่ใช้ (กันผลวัดเพี้ยน)
                skipped["in benchmark"] += 1
                continue
            # แบ่ง train/test ตามเลขทะเบียน (ไม่ใช่ตาม dataset): dataset มีภาพซ้ำของป้ายเดียวกันเยอะ (augment/เฟรมติดกัน)
            # ถ้าแบ่งตาม dataset ป้ายเดียวกันจะหลุดไปอยู่ทั้ง 2 ฝั่ง ทำให้ผลวัดดีเกินจริง
            split = "test" if int(hashlib.md5(text.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < 0.12 else "train"
            name = f"{split_dir}_{img.stem[:60]}{img.suffix}"
            shutil.copyfile(img, out / "crops" / name)
            rows.append({"file": f"crops/{name}", "text": text, "province": province, "status": "human",
                         "split": split, "source": img.name})
    with open(out / "labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    by = Counter(r["split"] for r in rows)
    print(f"✓ {out.relative_to(ROOT)}: {len(rows)} ป้าย (train {by['train']}, test {by['test']}) | "
          f"มีจังหวัด {sum(1 for r in rows if r['province'])} | ข้าม {dict(skipped)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--digits-from", default=None, help="รหัสของเลข 0 ถ้า dataset ใช้ A-code แทนตัวเลข เช่น A45")
    args = ap.parse_args()
    digits_from = int(args.digits_from[1:]) if args.digits_from else None
    sys.path.insert(0, str(ROOT / "training"))
    import benchmark

    exclude = {"".join(r["license_plate"].split()) for r in benchmark.load_gt(None)}
    convert(args.dataset, digits_from, exclude)


if __name__ == "__main__":
    main()
