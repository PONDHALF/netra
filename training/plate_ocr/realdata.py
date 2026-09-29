"""สร้างชุดป้ายจริงสำหรับเทรน PlateNet จาก dataset ที่มีแค่กรอบป้าย (ไม่มีเลขทะเบียน) — ติดคำตอบอัตโนมัติ

    python -m training.plate_ocr.realdata build data/datasets/car-with-plate
    python -m training.plate_ocr.realdata adjudicate data/datasets/real-plates/car-with-plate   # Typhoon ช่วยตัดสิน

ขั้นตอน
  1. ตัดภาพป้ายจากกรอบ (YOLO format) พร้อมขอบเผื่อแบบเดียวกับตัวตรวจจับของระบบ (8%)
  2. ให้ PlateNet + char-OCR อ่าน
     - อ่านตรงกันและครบรูปแบบ → "auto" (ถูก ~94% จากการวัดบนป้ายจริง) ใช้เทรนได้เลย
     - ขัดแย้ง/ไม่ครบ → "review" รอคนยืนยัน (หรือให้ Typhoon ช่วย)
  3. แบ่ง split ตามภาพต้นฉบับ (ป้ายจากภาพเดียวกันอยู่ split เดียวกัน): train 85% / test 15%

ผลลัพธ์: data/datasets/real-plates/<ชื่อ dataset>/
  crops/*.jpg   ภาพป้าย
  labels.csv    file, text, province, status(auto|review|human|reject), split, platenet, char, source
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT_ROOT = ROOT / "data" / "datasets" / "real-plates"
FIELDS = ["file", "text", "province", "status", "split", "platenet", "platenet_conf", "platenet_province", "char", "char_province",
          "typhoon", "typhoon_province", "province_conf", "source"]
norm = lambda s: "".join((s or "").split())  # noqa: E731


def _split_for(image_name: str, test_frac: float = 0.15) -> str:
    h = int(hashlib.md5(image_name.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < test_frac else "train"


def build(src: Path, device: str | None) -> Path:
    from engine.config import MODELS_DIR, auto_device
    from engine.ocr import CharPlateOCR
    from engine.platenet import PlateNetReader

    device = device or auto_device()
    pn = PlateNetReader(str(MODELS_DIR / "platenet.pt"), device)
    ch = CharPlateOCR(str(MODELS_DIR / "plate_ocr.pt"), device)
    out = OUT_ROOT / src.name
    (out / "crops").mkdir(parents=True, exist_ok=True)

    rows = []
    images = sorted(p for d in ("train", "valid", "test") for p in (src / d / "images").glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    for n, img_path in enumerate(images, 1):
        lab = img_path.parent.parent / "labels" / (img_path.stem + ".txt")
        if not lab.exists():
            continue
        im = cv2.imread(str(img_path))
        if im is None:
            continue
        H, W = im.shape[:2]
        for k, line in enumerate(l for l in lab.read_text().splitlines() if l.strip()):
            _, x, y, bw, bh = map(float, line.split()[:5])
            pw, ph = bw * W * 0.08, bh * H * 0.08
            x1, y1 = max(0, int((x - bw / 2) * W - pw)), max(0, int((y - bh / 2) * H - ph))
            x2, y2 = min(W, int((x + bw / 2) * W + pw)), min(H, int((y + bh / 2) * H + ph))
            if x2 - x1 < 24 or y2 - y1 < 10:
                continue
            crop = im[y1:y2, x1:x2]
            name = f"{hashlib.md5(img_path.name.encode()).hexdigest()[:12]}_{k}.jpg"
            cv2.imwrite(str(out / "crops" / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            p, c = pn.read(crop), ch.read(crop)
            agree = p.valid and c.valid and norm(p.text) == norm(c.text)
            # จังหวัด: ใช้เป็นคำตอบเฉพาะเมื่อ PlateNet กับ char-OCR ตรงกัน (ตรวจด้วยตาแล้ว: PlateNet อย่างเดียวผิดบ่อย
            # กับจังหวัดที่ไม่ใช่ กทม. เช่น ชลบุรี→แพร่) — ไม่งั้นเว้นว่าง (ตอนเทรนจะไม่คิด loss จังหวัด)
            prov = p.province if p.province and p.province == c.province else ""
            rows.append({
                "file": f"crops/{name}", "text": norm(p.text) if agree else "",
                "province": prov, "status": "auto" if agree else "review",
                "split": _split_for(img_path.name), "platenet": norm(p.text), "platenet_conf": round(p.conf, 3),
                "platenet_province": p.province or "", "char": norm(c.text), "char_province": c.province or "", "typhoon": "", "typhoon_province": "",
                "province_conf": round(p.province_conf, 3), "source": img_path.name,
            })
        if n % 200 == 0:
            print(f"  {n}/{len(images)} ภาพ", flush=True)

    with open(out / "labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    auto = sum(r["status"] == "auto" for r in rows)
    print(f"✓ ป้าย {len(rows)} ป้าย — อ่านตรงกัน (ใช้เทรนได้เลย) {auto} ({auto / max(len(rows), 1):.0%}), "
          f"รอตรวจ {len(rows) - auto} → {out.relative_to(ROOT)}/labels.csv")
    return out


def adjudicate(ds: Path, device: str | None) -> None:
    """ให้ Typhoon อ่านป้ายที่ยังไม่มีคำตอบ: ถ้าตรงกับ PlateNet หรือ char-OCR (2 ใน 3 เห็นตรงกัน) → ยอมรับ (auto2).
    จังหวัด: ถ้า Typhoon อ่านเลขได้ครบรูปแบบ และจังหวัดตรงกับ PlateNet หรือ char-OCR → ใช้."""
    from engine.config import auto_device
    from engine.typhoon import TyphoonOCR

    ty = TyphoonOCR(device or auto_device())
    path = ds / "labels.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    todo = [r for r in rows if r["status"] == "review" or (r["status"] == "auto" and not r["province"])]
    print(f"Typhoon อ่าน {len(todo)} ป้าย…", flush=True)
    accepted = prov_added = 0
    for n, r in enumerate(todo, 1):
        res = ty.read(cv2.imread(str(ds / r["file"])))
        r["typhoon"], r["typhoon_province"] = norm(res.text), res.province or ""
        if r["status"] == "review" and res.valid and r["typhoon"] in (r["platenet"], r["char"]) and r["typhoon"]:
            r["text"], r["status"] = r["typhoon"], "auto2"
            accepted += 1
        if not r["province"] and res.valid and res.province and res.province in (
                _platenet_province(r), r.get("char_province", "")):
            r["province"] = res.province
            prov_added += 1
        if n % 100 == 0:
            print(f"  {n}/{len(todo)}  ยอมรับเพิ่ม {accepted}  จังหวัดเพิ่ม {prov_added}", flush=True)
            _write(path, rows)
    _write(path, rows)
    ok = sum(r["status"] in ("auto", "auto2", "human") for r in rows)
    print(f"✓ ยอมรับเพิ่ม {accepted} ป้าย, จังหวัดเพิ่ม {prov_added} — มีคำตอบแล้ว {ok}/{len(rows)} ป้าย")


def _platenet_province(r: dict) -> str:
    return r.get("platenet_province", "") or ""


def _write(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("src", type=Path)
    b.add_argument("--device", default=None)
    a = sub.add_parser("adjudicate", help="ให้ Typhoon ช่วยตัดสินป้ายที่ขัดแย้ง (ต้องมี GPU + Typhoon)")
    a.add_argument("dataset", type=Path, help="เช่น data/datasets/real-plates/car-with-plate")
    a.add_argument("--device", default=None)
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.src, args.device)
    elif args.cmd == "adjudicate":
        adjudicate(args.dataset, args.device)


if __name__ == "__main__":
    main()
