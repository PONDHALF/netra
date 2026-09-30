"""วัดประสิทธิภาพระบบกล้องสด (StreamSession) บนไฟล์วิดีโอ — ป้อนเฟรมแบบกำหนดได้แน่นอน จึงเทียบก่อน/หลังแก้ได้ตรงๆ

    python -m training.stream_bench data/samples/live.mp4 --label baseline
    python -m training.stream_bench data/samples/live.mp4 --label ref --fps 30      # ทุกเฟรม (ค่าอ้างอิงสูงสุด)
    python -m training.stream_bench --compare baseline ref                          # เทียบ 2 รอบ (+ เฉลยถ้ามี)

วัด
  ความเร็ว   ms ต่อเฟรมแยกตามขั้น (ถอดรหัส / รถ / ป้าย / track+ocr / วาด) และ fps สูงสุดที่ทำได้
  การจับรถ   จำนวนรถ, อ่านป้ายได้, มั่นใจ ≥ 0.5, ป้ายเดียวกันถูกบันทึกซ้ำ
  ความถูกต้อง ถ้ามีเฉลย data/benchmark/stream/<ชื่อวิดีโอ>.gt.csv (time_sec, plate) — มีรถที่อ่านได้ตรงเฉลยในช่วง ±2 วินาทีไหม
             (live.gt.csv = เฉลยอัตโนมัติ: ป้ายที่ PlateNet + char-OCR อ่านตรงกันในรอบ ref ทุกเฟรม ถูก ~95% — ใช้เทียบว่า "ไม่แย่ลง")

ผลลัพธ์: data/benchmark/stream/<label>/{result.json, events.csv, plates/*.jpg}
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "benchmark" / "stream"
norm = lambda s: "".join((s or "").split()).replace("-", "")  # noqa: E731


def run(video: Path, label: str, fps: float | None, seconds: float | None) -> dict:
    import cv2

    from engine.config import EngineConfig
    from engine.pipeline import Engine
    from engine.stream import StreamSession

    out = OUT / label
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    cap = cv2.VideoCapture(str(video))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cfg = EngineConfig()
    target = fps or cfg.target_fps
    stride = max(1, round(src_fps / target))  # จำลองกล้องสด: ประมวลผลได้ target fps จากกล้อง src_fps
    eff_fps = src_fps / stride
    engine = Engine(cfg)

    events = []
    session = StreamSession(engine, out, fps=eff_fps, tag=label, out_width=960,
                            on_event=lambda ev, ts: events.append(ev))
    sums: Counter = Counter()
    orig_tick = session._tick

    def tick(name, t0):  # เก็บผลรวมจริง (session.timing เป็นค่าเฉลี่ยเคลื่อนที่)
        sums[name] += (time.perf_counter() - t0) * 1000
        return orig_tick(name, t0)

    session._tick = tick
    warm = 30  # เฟรมแรกๆ โหลดโมเดล/TensorRT — ไม่นับเวลา
    idx, n, t_dec, t_proc = -1, 0, 0.0, 0.0
    limit = int(seconds * src_fps) if seconds else None
    while True:
        t0 = time.perf_counter()
        ok, frame = cap.read()
        idx += 1
        if not ok or (limit and idx >= limit):
            break
        t_dec += (time.perf_counter() - t0) * 1000  # ทุกเฟรมต้องถอดรหัส แม้เฟรมที่ข้ามไม่ประมวลผล
        if idx % stride:
            continue
        t1 = time.perf_counter()
        session.process(frame)
        t_proc += (time.perf_counter() - t1) * 1000
        n += 1
        if n == warm:
            sums.clear()
            t_dec = t_proc = 0.0
    cap.release()
    session.close()
    timed = max(n - warm, 1)

    (out / "plates").mkdir(exist_ok=True)
    rows = []
    for ev in sorted(events, key=lambda e: e.first_seen_sec):
        if ev.plate_img:
            shutil.copyfile(out / ev.plate_img, out / "plates" / f"{ev.first_seen_sec:07.1f}_{ev.key}.jpg")
        rows.append({"first_sec": ev.first_seen_sec, "last_sec": ev.last_seen_sec, "best_sec": ev.video_offset_sec,
                     "type": ev.vehicle_type, "plate": ev.plate_text or "", "province": ev.plate_province or "",
                     "conf": ev.plate_conf, "engine": ev.ocr_engine or "", "key": ev.key})
    with open(out / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["first_sec"])
        w.writeheader()
        w.writerows(rows)

    ms = {k: round(v / timed, 2) for k, v in sums.items()}
    ms["decode"] = round(t_dec / timed, 2)
    ms["total"] = round((t_dec + t_proc) / timed, 2)
    res = {"label": label, "video": video.name, "src_fps": src_fps, "stride": stride, "eff_fps": round(eff_fps, 2),
           "frames": n, "ms_per_frame": ms, "max_fps": round(1000 / max(ms["total"], 1e-6), 1),
           **summarize(rows), "device": cfg.device}
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def summarize(rows: list[dict]) -> dict:
    read = [r for r in rows if r["plate"]]
    counts = Counter(norm(r["plate"]) for r in read)
    return {"vehicles": len(rows), "plates_read": len(read), "confident": sum(r["conf"] >= 0.5 for r in read),
            "duplicate_plates": sum(c - 1 for c in counts.values() if c > 1)}


def load_rows(label: str) -> list[dict]:
    rows = list(csv.DictReader(open(OUT / label / "events.csv", encoding="utf-8")))
    for r in rows:
        for k in ("first_sec", "last_sec", "best_sec", "conf"):
            r[k] = float(r[k])
    return rows


def accuracy(rows: list[dict], gt: list[dict], tol: float = 2.0) -> dict:
    """เฉลย = รถที่คนอ่านป้ายได้ (time_sec = เวลาที่เห็นป้ายชัด). จับคู่ event ที่ช่วงเวลาครอบคลุม ±tol."""
    used, found, correct = set(), 0, 0
    for g in gt:
        t, plate = float(g["time_sec"]), norm(g["plate"])
        cands = [i for i, r in enumerate(rows) if i not in used and r["first_sec"] - tol <= t <= r["last_sec"] + tol]
        if not cands:
            continue
        # คันที่อ่านได้ตรงเฉลยก่อน ไม่งั้นคันที่เวลาใกล้สุด
        i = next((i for i in cands if norm(rows[i]["plate"]) == plate),
                 min(cands, key=lambda i: abs(rows[i]["best_sec"] - t)))
        used.add(i)
        found += 1
        correct += norm(rows[i]["plate"]) == plate
    n = max(len(gt), 1)
    return {"gt": len(gt), "found": found, "found_rate": round(found / n, 3), "correct": correct,
            "correct_rate": round(correct / n, 3)}


def compare(labels: list[str]) -> None:
    table = []
    for lb in labels:
        res = json.loads((OUT / lb / "result.json").read_text())
        rows = load_rows(lb)
        gt_path = OUT / (Path(res["video"]).stem + ".gt.csv")
        acc = accuracy(rows, list(csv.DictReader(open(gt_path, encoding="utf-8")))) if gt_path.exists() else None
        table.append((lb, res, acc))
    print(f"{'รอบ':14} {'fps ใช้':>7} {'ms/เฟรม':>8} {'fps สูงสุด':>10} {'รถ':>5} {'อ่านได้':>7} {'มั่นใจ':>6} {'ซ้ำ':>4}"
          f"{'  อ่านตรงเฉลย':>16}")
    for lb, r, acc in table:
        a = f"  {acc['correct']}/{acc['gt']} ({acc['correct_rate']:.0%})" if acc else ""
        print(f"{lb:14} {r['eff_fps']:>7} {r['ms_per_frame']['total']:>8} {r['max_fps']:>10} {r['vehicles']:>5} "
              f"{r['plates_read']:>7} {r['confident']:>6} {r['duplicate_plates']:>4}{a}")
    for lb, r, _ in table:
        print(f"  {lb}: " + ", ".join(f"{k} {v}" for k, v in r["ms_per_frame"].items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?", type=Path)
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--fps", type=float, default=None, help="fps ที่ประมวลผล (ค่าเริ่มต้น = target_fps ของระบบ)")
    ap.add_argument("--seconds", type=float, default=None, help="ใช้แค่ N วินาทีแรก")
    ap.add_argument("--compare", nargs="+", metavar="LABEL")
    args = ap.parse_args()
    if args.compare:
        compare(args.compare)
        return
    res = run(args.video, args.label, args.fps, args.seconds)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
