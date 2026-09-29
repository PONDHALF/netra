"""รัน engine ผ่านคำสั่ง:  python -m engine.cli video.mp4 --out data/outputs/test

ผลลัพธ์: <out>/events.csv, <out>/events/*.jpg, <out>/annotated.mp4
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from .config import EngineConfig
from .pipeline import Engine, Progress, VehicleEvent


def main() -> None:
    ap = argparse.ArgumentParser(description="NETRA — ประมวลผลวิดีโอ ตรวจจับรถและอ่านป้ายทะเบียน")
    ap.add_argument("video")
    ap.add_argument("--out", default=None, help="โฟลเดอร์ผลลัพธ์ (ค่าเริ่มต้น data/outputs/<ชื่อไฟล์>)")
    ap.add_argument("--device", default=None, help="cpu / mps / cuda:0")
    ap.add_argument("--stride", type=int, default=None, help="ประมวลผลทุกๆ N เฟรม")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = EngineConfig()
    if args.device:
        cfg.device = args.device
    if args.stride:
        cfg.frame_stride = args.stride
    out = Path(args.out or Path("data/outputs") / Path(args.video).stem)

    engine = Engine(cfg)

    def on_event(ev: VehicleEvent) -> None:
        print(f"\r  [{ev.video_offset_sec:7.1f}s] #{ev.track_id:<4} {ev.vehicle_type:<10} "
              f"{ev.plate_text or '-':<10} {ev.plate_province or '':<16} {ev.plate_conf:.0%}", flush=True)

    def on_progress(p: Progress) -> None:
        eta = f"{p.eta_sec:.0f}s" if p.eta_sec else "?"
        sys.stderr.write(f"\r{p.stage:<10} {p.progress:6.1%}  {p.fps:5.1f} fps  eta {eta:<6}  events {p.events}")
        sys.stderr.flush()

    events: list[VehicleEvent] = []
    summary = engine.process(args.video, out, on_event=lambda e: (events.append(e), on_event(e)),
                             on_progress=on_progress)
    sys.stderr.write("\n")

    with open(out / "events.csv", "w", newline="", encoding="utf-8-sig") as f:
        fields = list(VehicleEvent.__dataclass_fields__)
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in events:
            w.writerow(e.to_dict())
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    read = sum(1 for e in events if e.plate_text)
    print(f"\nเสร็จ: รถ {len(events)} คัน, อ่านป้ายได้ {read} ({read / max(len(events), 1):.0%}) "
          f"ใช้เวลา {summary['elapsed_sec']}s → {out}")


if __name__ == "__main__":
    main()
