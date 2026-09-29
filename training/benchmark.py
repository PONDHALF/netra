"""วัดความแม่นยำของ engine บนภาพจริงที่มีเฉลย (ใช้เทียบก่อน/หลังปรับโมเดลทุกครั้ง)

    python training/benchmark.py              # ดาวน์โหลดชุดทดสอบอัตโนมัติ (ครั้งแรก) แล้ววัดผล
    python training/benchmark.py --show       # แสดงรายการที่อ่านผิด
    python training/benchmark.py --mode crops # วัดเฉพาะ OCR บนภาพป้ายที่ตัดไว้แล้ว

ชุดทดสอบ: thai-parking-100 — ภาพจากกล้องลานจอด 2560x1440 จำนวน 100 ภาพ พร้อมเลขทะเบียนและจังหวัดที่ถูกต้อง
(จาก github.com/THIRAPHATCHAKON/PaddleOCR_LicenseTH, MIT License)

2 แบบที่วัด
  e2e   ภาพเต็ม → ตรวจจับรถ → หาป้าย → OCR  (ขั้นตอนเดียวกับ pipeline แต่ไม่มี vote หลายเฟรม)
        ถ้ามีรถหลายคันในภาพ จะนับคันที่ตรงกับเฉลยที่สุด (เพราะ pipeline บันทึกทุกคัน)
  crops ภาพป้ายที่ตัดไว้แล้ว → OCR          (วัดเฉพาะความสามารถในการอ่าน)

ผลแต่ละครั้งบันทึกที่ data/benchmark/results/ และแสดงผลต่างจากครั้งก่อนให้อัตโนมัติ
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATASET = "thai-parking-100"
REPO = "THIRAPHATCHAKON/PaddleOCR_LicenseTH"
COMMIT = "10aafda015887a5106e7934ba94f12181c8ed3a0"  # ตรึงเวอร์ชันไว้ ให้ผลเทียบกันได้
BENCH_DIR = ROOT / "data" / "benchmark"
DATA_DIR = BENCH_DIR / DATASET
RESULTS_DIR = BENCH_DIR / "results"
MAX_VEHICLES = 4


# ----------------------------------------------------------------------------- dataset
def download() -> None:
    socket.setdefaulttimeout(60)  # กันค้างถ้าเครือข่ายไม่ตอบ
    raw = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/evaluation_ocr"
    (DATA_DIR / "plate").mkdir(parents=True, exist_ok=True)
    gt = DATA_DIR / "ground_truth.csv"
    if not gt.exists():
        urllib.request.urlretrieve(f"{raw}/ground_truth.csv", gt)
    names = [r["image"] for r in csv.DictReader(open(gt, encoding="utf-8"))]
    jobs = [(f"{raw}/{n}", DATA_DIR / n) for n in names] + [(f"{raw}/plate/{n}", DATA_DIR / "plate" / n) for n in names]
    jobs = [(u, p) for u, p in jobs if not p.exists()]
    if not jobs:
        return
    print(f"ดาวน์โหลดชุดทดสอบ {DATASET} ({len(jobs)} ไฟล์)…")

    def fetch(job):
        url, path = job
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(path)

    with ThreadPoolExecutor(16) as ex:
        list(ex.map(fetch, jobs))


def load_gt(limit: int | None) -> list[dict]:
    rows = list(csv.DictReader(open(DATA_DIR / "ground_truth.csv", encoding="utf-8")))
    return rows[:limit] if limit else rows


# ----------------------------------------------------------------------------- metrics
def norm(s: str | None) -> str:
    return "".join((s or "").split())


def char_acc(pred: str, truth: str) -> float:
    """1 - (edit distance / ความยาวเฉลย) — ใช้ดูความคืบหน้าแม้ยังไม่ถูกทั้งป้าย."""
    a, b = norm(pred), norm(truth)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return max(0.0, 1 - prev[-1] / max(len(b), 1))


def summarize(rows: list[dict]) -> dict:
    n = max(len(rows), 1)
    return {
        "n": len(rows),
        "plate_text": sum(r["text_ok"] for r in rows) / n,
        "province": sum(r["prov_ok"] for r in rows) / n,
        "both": sum(r["text_ok"] and r["prov_ok"] for r in rows) / n,
        "char_acc": sum(r["char_acc"] for r in rows) / n,
        "vehicle_found": sum(r.get("vehicle", True) for r in rows) / n,
        "plate_found": sum(r.get("plate", True) for r in rows) / n,
        "ms_per_image": sum(r["ms"] for r in rows) / n,
    }


# ----------------------------------------------------------------------------- runners
def run_crops(engine, gt: list[dict]) -> list[dict]:
    out = []
    for r in gt:
        img = cv2.imread(str(DATA_DIR / "plate" / r["image"]))
        t = time.perf_counter()
        pred = engine.reader.read_plate(img)
        if engine.cfg.typhoon:
            pred = engine.refine_with_typhoon(pred, img)
        out.append(_row(r, pred.text, pred.province, t))
    return out


def run_e2e(engine, gt: list[dict]) -> list[dict]:
    """ทำตามขั้นตอนเดียวกับ Engine: รถ → ป้าย (โมเดลป้าย หรือโหมดสำรอง) → OCR."""
    from engine.config import VEHICLE_CLASSES
    from engine.detectors import Box, assign_plates
    from engine.pipeline import _clip

    cfg = engine.cfg
    out = []
    for r in gt:
        frame = cv2.imread(str(DATA_DIR / r["image"]))
        H, W = frame.shape[:2]
        t = time.perf_counter()
        res = engine.tracker.model.predict(frame, classes=list(VEHICLE_CLASSES), conf=cfg.vehicle_conf,
                                           imgsz=cfg.imgsz, device=cfg.device, verbose=False)[0]
        vehicles = [(i, VEHICLE_CLASSES[int(c)], Box(*b, float(cf))) for i, (b, c, cf) in
                    enumerate(zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()))]
        plates = engine.plates.detect(frame) if engine.plates.available else []
        tracked = assign_plates(vehicles, plates)
        # pipeline บันทึกรถทุกคันในภาพ แต่เฉลยมีแค่คันเดียว → อ่านทุกคัน (สูงสุด 4 คันที่ใหญ่สุด)
        # แล้วนับผลของคันที่ตรงกับเฉลยที่สุด
        readings = []
        for v in sorted(tracked, key=lambda v: -v.box.area)[:MAX_VEHICLES]:
            if v.plate:
                x1, y1, x2, y2 = _clip(v.plate, W, H, pad=0.08)
                crop = frame[y1:y2, x1:x2]
                pred, found = engine.reader.read_plate(crop), True
                if engine.cfg.typhoon:
                    pred = engine.refine_with_typhoon(pred, crop)
            else:
                x1, y1, x2, y2 = _clip(v.box, W, H, pad=0.04)
                pred, box = engine.reader.find_and_read(frame[y1:y2, x1:x2])
                found = box is not None
            readings.append((pred, found))
        if readings:
            pred, has_plate = max(readings, key=lambda pf: (
                char_acc(pf[0].text or "", r["license_plate"]) + (pf[0].province == r["province"]) * 0.01))
            text, prov = pred.text, pred.province
        else:
            text = prov = None
            has_plate = False
        row = _row(r, text, prov, t)
        row.update(vehicle=bool(tracked), plate=has_plate)
        out.append(row)
    return out


def _row(r: dict, text: str | None, prov: str | None, t0: float) -> dict:
    return {
        "image": r["image"], "truth": r["license_plate"], "truth_prov": r["province"],
        "pred": text, "pred_prov": prov,
        "text_ok": norm(text) == norm(r["license_plate"]), "prov_ok": (prov or "") == r["province"],
        "char_acc": char_acc(text or "", r["license_plate"]), "ms": (time.perf_counter() - t0) * 1000,
    }


# ----------------------------------------------------------------------------- report
def fmt_delta(cur: float, prev: float | None, pct: bool = True) -> str:
    if prev is None:
        return ""
    d = cur - prev
    if abs(d) < 1e-9:
        return "  (เท่าเดิม)"
    s = f"{d * 100:+.1f}" if pct else f"{d:+.0f}"
    return f"  ({s})"


def print_report(mode: str, m: dict, prev: dict | None) -> None:
    title = {"e2e": "ภาพเต็ม → รถ → ป้าย → OCR", "crops": "OCR บนภาพป้ายที่ตัดไว้แล้ว"}[mode]
    print(f"\n── {mode}: {title}  ({m['n']} ภาพ)")
    lines = [("อ่านเลขทะเบียนถูกทั้งป้าย", "plate_text"), ("จังหวัดถูก", "province"),
             ("ถูกทั้งเลขและจังหวัด", "both"), ("ความถูกต้องรายตัวอักษร", "char_acc")]
    if mode == "e2e":
        lines += [("พบรถ", "vehicle_found"), ("พบป้าย", "plate_found")]
    for label, k in lines:
        print(f"   {label:<26} {m[k] * 100:6.1f}%{fmt_delta(m[k], prev.get(k) if prev else None)}")
    print(f"   {'เวลาเฉลี่ย':<26} {m['ms_per_image']:6.0f} ms/ภาพ"
          f"{fmt_delta(m['ms_per_image'], prev.get('ms_per_image') if prev else None, pct=False)}")


def last_result() -> dict | None:
    files = sorted(RESULTS_DIR.glob("*.json"))
    return json.loads(files[-1].read_text()) if files else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["all", "e2e", "crops"], default="all")
    ap.add_argument("--show", action="store_true", help="แสดงรายการที่อ่านผิด")
    ap.add_argument("--limit", type=int, default=None, help="ใช้แค่ N ภาพแรก (ทดสอบเร็ว)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--no-save", action="store_true", help="ไม่บันทึกผลครั้งนี้")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    download()
    gt = load_gt(args.limit)

    from engine import Engine, EngineConfig

    cfg = EngineConfig()
    if args.device:
        cfg.device = args.device
    engine = Engine(cfg)
    config = {"device": cfg.device, "plate_model": engine.plates.available,
              "plate_model_path": cfg.plate_model if engine.plates.available else None,
              "reader": ("char-ocr + easyocr" if engine.reader.char else "easyocr")
              + (" + typhoon" if engine.cfg.typhoon else "")}
    print(f"engine: device={cfg.device}  plate_model={'มี' if engine.plates.available else 'ไม่มี (โหมดสำรอง)'}"
          f"  reader={config['reader']}")

    prev = last_result()
    comparable = prev if prev and prev.get("n") == len(gt) else None
    if comparable:
        print(f"เทียบกับผลครั้งก่อน: {comparable['time']}  (ตัวเลขในวงเล็บ = ผลต่าง จุด %)")

    engine.reader.read_plate(cv2.imread(str(DATA_DIR / "plate" / gt[0]["image"])))  # warm-up
    result = {"time": datetime.now().isoformat(timespec="seconds"), "dataset": DATASET, "n": len(gt),
              "config": config, "metrics": {}, "rows": {}}
    modes = ["e2e", "crops"] if args.mode == "all" else [args.mode]
    for mode in modes:
        rows = (run_e2e if mode == "e2e" else run_crops)(engine, gt)
        m = summarize(rows)
        result["metrics"][mode], result["rows"][mode] = m, rows
        print_report(mode, m, comparable["metrics"].get(mode) if comparable else None)
        if args.show:
            bad = [r for r in rows if not (r["text_ok"] and r["prov_ok"])]
            print(f"   ✗ ผิด {len(bad)} รายการ:")
            for r in bad:
                mark_t = "✓" if r["text_ok"] else "✗"
                mark_p = "✓" if r["prov_ok"] else "✗"
                print(f"     {r['image']}  เฉลย {r['truth']:<9} {r['truth_prov']:<14} "
                      f"อ่านได้ {mark_t} {r['pred'] or '-':<10} {mark_p} {r['pred_prov'] or '-'}")

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(f"\nบันทึกผล → {path.relative_to(ROOT)}")
    print("เป้าหมาย Phase 1: อ่านถูกทั้งป้าย ≥ 80% (กลางวัน ป้ายชัด)")


if __name__ == "__main__":
    main()
