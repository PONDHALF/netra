"""ทดลอง Typhoon OCR 3B (typhoon-ai/typhoon-ocr-3b) อ่านป้ายทะเบียน เทียบกับตัวอ่านปัจจุบัน

    python training/eval_typhoon.py --limit 10     # ลองเร็วๆ
    python training/eval_typhoon.py --show         # ทั้ง 100 ภาพ + แสดงรายการที่ผิด

ใช้ภาพป้ายที่ตัดไว้แล้วจากชุดทดสอบ thai-parking-100 (โหมด crops ของ benchmark.py)
โมเดลนี้ต้องใช้ prompt เฉพาะของ Typhoon ("default") และตอบเป็น JSON {"natural_text": ...}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))

import benchmark  # noqa: E402
from engine.postprocess import PlateReading  # noqa: E402
from engine.typhoon import TyphoonOCR, to_reading  # noqa: E402

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--device", default=None)
    ap.add_argument("--height", type=int, default=256, help="ขยายภาพป้ายให้สูงเท่านี้ก่อนส่งเข้าโมเดล")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    from engine.config import MODELS_DIR, auto_device
    from engine.ocr import CharPlateOCR

    device = args.device or auto_device()
    benchmark.download()
    gt = benchmark.load_gt(args.limit)
    crops = [cv2.imread(str(benchmark.DATA_DIR / "plate" / r["image"])) for r in gt]
    crops = [cv2.resize(c, None, fx=args.height / c.shape[0], fy=args.height / c.shape[0],
                        interpolation=cv2.INTER_CUBIC) if c.shape[0] < args.height else c for c in crops]

    t0 = time.time()
    typhoon = TyphoonOCR(device)
    print(f"โหลด Typhoon OCR 3B บน {device}: {time.time() - t0:.0f}s")
    char = CharPlateOCR(str(MODELS_DIR / "plate_ocr.pt"), device)

    results = {"typhoon": [], "char": [], "char+typhoon": []}
    for i, (r, c) in enumerate(zip(gt, crops), 1):
        t = time.perf_counter()
        raw = typhoon.raw(c)
        ty = to_reading(raw)
        ms_ty = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        ch = char.read(c)
        ms_ch = (time.perf_counter() - t) * 1000
        # รวม: เลขจากโมเดลรายตัวอักษรถ้าครบรูปแบบ ไม่งั้นใช้ Typhoon, จังหวัดจาก Typhoon ก่อน
        hy = PlateReading(text=ch.text if ch.valid else (ty.text or ch.text),
                          province=ty.province or ch.province)
        for name, pred, ms in (("typhoon", ty, ms_ty), ("char", ch, ms_ch), ("char+typhoon", hy, ms_ty + ms_ch)):
            row = benchmark._row(r, pred.text, pred.province, time.perf_counter())
            row["ms"] = ms
            row["raw"] = raw if name == "typhoon" else ""
            results[name].append(row)
        print(f"\r{i}/{len(gt)}  {ms_ty:.0f} ms", end="", flush=True)
    print()

    print(f"\n{'ตัวอ่าน':<14} {'เลขถูก':>8} {'จังหวัดถูก':>11} {'ถูกทั้งคู่':>10} {'รายตัวอักษร':>12} {'เวลา/ป้าย':>10}")
    for name, rows in results.items():
        m = benchmark.summarize(rows)
        print(f"{name:<14} {m['plate_text']:>8.0%} {m['province']:>11.0%} {m['both']:>10.0%} "
              f"{m['char_acc']:>12.0%} {m['ms_per_image']:>8.0f}ms")

    if args.show:
        print("\nTyphoon — รายการที่ผิด:")
        for row in results["typhoon"]:
            if not (row["text_ok"] and row["prov_ok"]):
                print(f"  {row['image']}  เฉลย {row['truth']} {row['truth_prov']:<14} อ่านได้ {row['pred'] or '-'} "
                      f"{row['pred_prov'] or '-':<14} raw={row['raw'][:80]!r}")

    out = benchmark.BENCH_DIR / "typhoon" / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({k: {"metrics": benchmark.summarize(v), "rows": v} for k, v in results.items()},
                              ensure_ascii=False, indent=1))
    print(f"\nบันทึกผล → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
