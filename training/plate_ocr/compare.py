"""เทียบวิธีรวมผล PlateNet กับ char-OCR บนภาพป้ายจริง (thai-parking-100) เพื่อเลือกนโยบายที่ดีที่สุด

    python -m training.plate_ocr.compare --model data/train/platenet/best.pt
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))

import benchmark  # noqa: E402
from engine.config import MODELS_DIR, auto_device  # noqa: E402
from engine.ocr import CharPlateOCR  # noqa: E402
from engine.platenet import PlateNetReader  # noqa: E402

norm = lambda s: "".join((s or "").split())  # noqa: E731


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(ROOT / "data" / "train" / "platenet" / "best.pt"))
    ap.add_argument("--device", default=None)
    args = ap.parse_args()
    device = args.device or auto_device()

    benchmark.download()
    gt = benchmark.load_gt(None)
    crops = [cv2.imread(str(benchmark.DATA_DIR / "plate" / r["image"])) for r in gt]
    pn = PlateNetReader(args.model, device)
    ch = CharPlateOCR(str(MODELS_DIR / "plate_ocr.pt"), device)

    pn.read_batch(crops[:4])
    t = time.perf_counter()
    P = [pn.read(c) for c in crops]
    t_pn = (time.perf_counter() - t) / len(crops) * 1000
    t = time.perf_counter()
    C = [ch.read(c) for c in crops]
    t_ch = (time.perf_counter() - t) / len(crops) * 1000

    def score(name, picks):
        t_ok = sum(norm(txt) == norm(r["license_plate"]) for (txt, _), r in zip(picks, gt))
        p_ok = sum((prov or "") == r["province"] for (_, prov), r in zip(picks, gt))
        both = sum(norm(txt) == norm(r["license_plate"]) and (prov or "") == r["province"]
                   for (txt, prov), r in zip(picks, gt))
        print(f"  {name:<44} เลข {t_ok:3d}%  จังหวัด {p_ok:3d}%  ทั้งคู่ {both:3d}%")

    print(f"PlateNet {t_pn:.1f} ms/ป้าย | char-OCR {t_ch:.1f} ms/ป้าย  ({device})")
    agree = sum(p.valid and c.valid and norm(p.text) == norm(c.text) for p, c in zip(P, C))
    agree_ok = sum(p.valid and c.valid and norm(p.text) == norm(c.text) and norm(p.text) == norm(r["license_plate"])
                   for p, c, r in zip(P, C, gt))
    print(f"อ่านตรงกัน {agree} ป้าย — ในนั้นถูกจริง {agree_ok} ({agree_ok / max(agree, 1):.0%})\n")

    score("char-OCR อย่างเดียว", [(c.text, c.province) for c in C])
    score("PlateNet อย่างเดียว", [(p.text, p.province) for p in P])

    def combo(tie: str, prov: str, min_pconf: float = 0.0):
        out = []
        for p, c in zip(P, C):
            if p.valid and c.valid:
                if norm(p.text) == norm(c.text):
                    txt = p.text
                elif tie == "platenet":
                    txt = p.text
                else:  # conf สูงกว่า
                    txt = p.text if p.conf >= c.conf else c.text
            else:
                txt = p.text if p.valid else (c.text if c.valid else (p.text or c.text))
            if prov == "platenet":
                pr = p.province if p.province_conf >= min_pconf or not c.province else c.province
            else:
                pr = c.province or p.province
            out.append((txt, pr))
        return out

    score("รวม: ขัดแย้ง→PlateNet, จังหวัด PlateNet", combo("platenet", "platenet"))
    score("รวม: ขัดแย้ง→conf สูงกว่า, จังหวัด PlateNet", combo("conf", "platenet"))
    for th in (0.3, 0.5, 0.7):
        score(f"รวม: ขัดแย้ง→PlateNet, จังหวัด PN (conf≥{th} ไม่งั้น char)", combo("platenet", "platenet", th))
    score("รวม: ขัดแย้ง→PlateNet, จังหวัด char ก่อน", combo("platenet", "char"))


if __name__ == "__main__":
    main()
