"""วัดความแม่นยำการอ่านป้าย (ทั้งป้าย) จากข้อมูลที่แก้ไขด้วยมือใน data/corrections/

    python training/eval_ocr.py            # ใช้ data/corrections/labels.csv
    python training/eval_ocr.py --show     # แสดงรายการที่อ่านผิด

เกณฑ์ Phase 1: อ่านถูกทั้งป้าย ≥ 80% (กลางวัน ป้ายชัด)
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def norm(s: str | None) -> str:
    return "".join((s or "").split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "corrections"))
    ap.add_argument("--device", default=None)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    from engine.config import auto_device
    from engine.ocr import PlateReader

    base = Path(args.dir)
    rows = list(csv.DictReader(open(base / "labels.csv", encoding="utf-8")))
    if not rows:
        raise SystemExit("ยังไม่มีข้อมูล — แก้ไขเลขทะเบียนในหน้าเว็บก่อน")
    reader = PlateReader(args.device or auto_device())
    ok_text = ok_prov = 0
    for r in rows:
        img = cv2.imread(str(base / r["image"]))
        pred = reader.read_plate(img)
        t_ok = norm(pred.text) == norm(r["plate_text"])
        p_ok = (pred.province or "") == (r["plate_province"] or "")
        ok_text += t_ok
        ok_prov += p_ok
        if args.show and not (t_ok and p_ok):
            print(f"  ✗ {r['image']}: จริง={r['plate_text']} {r['plate_province']}  อ่านได้={pred.text} {pred.province}")
    n = len(rows)
    print(f"\nจำนวน {n} ป้าย")
    print(f"  เลขทะเบียนถูกทั้งป้าย : {ok_text / n:.1%}")
    print(f"  จังหวัดถูก           : {ok_prov / n:.1%}")


if __name__ == "__main__":
    main()
