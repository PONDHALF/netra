"""สร้างวิดีโอสาธิตจากภาพกล้องลานจอดจริงในชุดทดสอบ thai-parking-100 (ใช้ระหว่างยังไม่มีวิดีโอจริง)

    python training/make_demo_video.py                 # 20 ภาพ → data/samples/demo_parking.mp4
    python training/make_demo_video.py --frames 40 --hold 2

แต่ละภาพค้างไว้ --hold วินาที เหมือนรถจอดที่ไม้กั้นทีละคัน — ใช้ทดสอบระบบทั้งเส้นทาง
(อัปโหลด → ตรวจจับ → อ่านป้าย → หน้าผลลัพธ์) ได้ แต่ไม่มีการเคลื่อนที่จริง
จึงไม่ได้ทดสอบการติดตามรถ (tracking) และการ vote หลายเฟรมแบบวิดีโอจริง
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

import benchmark  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=int, default=20, help="จำนวนภาพ (สูงสุด 100)")
    ap.add_argument("--hold", type=float, default=1.5, help="วินาทีต่อภาพ")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--out", default=str(ROOT / "data" / "samples" / "demo_parking.mp4"))
    args = ap.parse_args()

    import imageio_ffmpeg

    benchmark.download()
    rows = benchmark.load_gt(args.frames)
    first = cv2.imread(str(benchmark.DATA_DIR / rows[0]["image"]))
    h, w = first.shape[:2]
    ow, oh = args.width // 2 * 2, int(args.width * h / w) // 2 * 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    writer = imageio_ffmpeg.write_frames(
        str(out), (ow, oh), fps=args.fps, codec="libx264", pix_fmt_in="bgr24", pix_fmt_out="yuv420p",
        quality=None, macro_block_size=2, ffmpeg_log_level="error",
        output_params=["-crf", "20", "-movflags", "+faststart"],
    )
    writer.send(None)
    per = max(1, round(args.hold * args.fps))
    for r in rows:
        frame = cv2.resize(cv2.imread(str(benchmark.DATA_DIR / r["image"])), (ow, oh), interpolation=cv2.INTER_AREA)
        for _ in range(per):
            writer.send(frame)
    writer.close()

    labels = out.with_suffix(".csv")
    with open(labels, "w", encoding="utf-8") as f:
        f.write("second,license_plate,province\n")
        for i, r in enumerate(rows):
            f.write(f"{i * per / args.fps:.1f},{r['license_plate']},{r['province']}\n")
    print(f"✓ {out.relative_to(ROOT)}  ({len(rows)} ภาพ, {len(rows) * per / args.fps:.0f} วินาที)")
    print(f"  เฉลย → {labels.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
