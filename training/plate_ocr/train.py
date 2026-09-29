"""เทรน PlateNet ด้วยป้ายจำลอง แล้ววัดผลกับป้ายจริง (thai-parking-100 — ใช้วัดผลเท่านั้น ไม่ได้ใช้เทรน)

    python -m training.plate_ocr.train                    # ค่าเริ่มต้น (GPU)
    python -m training.plate_ocr.train --steps 300 --batch 32 --device cpu --workers 4   # ทดสอบเร็ว

ผลลัพธ์ใน data/train/platenet/
  log.jsonl   บันทึกทุกครั้งที่วัดผล (loss, ความแม่นยำบนป้ายจริง/จำลอง)
  best.pt     โมเดลที่ดีที่สุดบนป้ายจริง (ถูกทั้งเลขและจังหวัด → เลข → รายตัวอักษร)
  last.pt     จุดล่าสุด (ใช้ --resume เทรนต่อ)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))

from engine.platenet import (INPUT_H, INPUT_W, PROVINCE_CLASSES, build_model, ctc_greedy, encode,  # noqa: E402
                             format_plate, preprocess)
from training.plate_ocr.synth import available_fonts, degrade, make_sample  # noqa: E402

OUT = ROOT / "data" / "train" / "platenet"
FONT_DIR = ROOT / "data" / "fonts"


# ------------------------------------------------------------------ data
IGNORE = -100  # ไม่มีคำตอบจังหวัด → ไม่คิด loss ส่วนจังหวัด


REAL_STATUSES = ("auto", "human")  # "auto2" (Typhoon ตัดสิน) ตรวจแล้วผิด ~10% (ฒ↔ต) — ไม่ใช้เป็นค่าเริ่มต้น


def load_real_rows(dirs: list[str], split: str, statuses=REAL_STATUSES) -> list[tuple[str, str, int]]:
    """ป้ายจริงที่มีคำตอบแล้ว (auto / auto2 / human) จาก labels.csv ของ training/plate_ocr/realdata.py."""
    import csv as _csv

    out = []
    for d in dirs:
        base = ROOT / d
        for r in _csv.DictReader(open(base / "labels.csv", encoding="utf-8")):
            if r["split"] != split or r["status"] not in statuses or not r["text"]:
                continue
            prov = PROVINCE_CLASSES.index(r["province"]) if r["province"] in PROVINCE_CLASSES else IGNORE
            out.append((str(base / r["file"]), r["text"].replace("-", ""), prov))
    return out


class SynthStream(torch.utils.data.IterableDataset):
    """ป้ายจำลองไม่รู้จบ ผสมป้ายจริง (ถ้ามี) — แต่ละ worker สุ่มด้วย seed ของตัวเอง (ต้องอยู่ระดับ module ให้ spawn/pickle ได้)
    ป้ายจริงถูกทำให้เสื่อมแบบเดียวกับป้ายจำลอง (ภาพใน dataset ชัดกว่ากล้องวงจรปิดมาก)."""

    def __init__(self, seed: int, real: list | None = None, real_ratio: float = 0.0):
        """real: [(ภาพ RGB uint8, เลขทะเบียน, จังหวัด)] — โหลดครั้งเดียวใน process หลักก่อนแยก worker
        (fork แชร์หน่วยความจำแบบอ่านอย่างเดียว) — ห้ามให้แต่ละ worker cache เอง: เคยทำให้แรมโตจน OOM ที่ ~step 5000"""
        self.seed, self.real, self.real_ratio = seed, real or [], real_ratio

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        wid = info.id if info else 0
        rng = random.Random(self.seed * 1000 + wid)
        np.random.seed((self.seed * 1000 + wid) % 2**32)
        fonts = available_fonts(FONT_DIR)
        from PIL import Image

        while True:
            if self.real and rng.random() < self.real_ratio:
                rgb, text, prov = self.real[rng.randrange(len(self.real))]
                img_u8 = degrade(rng, Image.fromarray(rgb))
            else:
                s = make_sample(rng, fonts)
                img_u8, text, prov = s.image, s.text, s.province
            img = img_u8.astype(np.float32) / 127.5 - 1.0
            yield img.transpose(2, 0, 1), encode(text), prov


def worker_init(_):
    """1 thread ต่อ worker — ไม่งั้น torch ในแต่ละ worker แตก thread เท่าจำนวน core
    (48 worker × 72 thread บนเครื่อง Xeon แย่ง CPU กันจนเหลือ ~110 ภาพ/วินาที)
    หมายเหตุ: ห้ามเรียก cv2.setNumThreads ที่นี่ — เรียกใน process ลูกหลัง fork ทำให้ OpenCV ค้าง
    จึงตั้งไว้ครั้งเดียวใน main() ก่อนใช้ OpenCV แล้วให้ worker สืบทอดไป"""
    torch.set_num_threads(1)


def collate(batch):
    import torch

    imgs = torch.from_numpy(np.stack([b[0] for b in batch]))
    targets = torch.tensor([t for b in batch for t in b[1]], dtype=torch.long)
    lengths = torch.tensor([len(b[1]) for b in batch], dtype=torch.long)
    provs = torch.tensor([b[2] for b in batch], dtype=torch.long)
    return imgs, targets, lengths, provs


def load_real() -> list[tuple[np.ndarray, str, int]]:
    """ป้ายจริงพร้อมเฉลย: thai-parking-100 (ภาพป้ายที่ตัดแล้ว) + data/corrections (ที่ผู้ใช้แก้ในหน้าเว็บ)."""
    import benchmark

    benchmark.download()
    out = []
    for r in benchmark.load_gt(None):
        img = cv2.imread(str(benchmark.DATA_DIR / "plate" / r["image"]))
        prov = PROVINCE_CLASSES.index(r["province"]) if r["province"] in PROVINCE_CLASSES else -1
        out.append((img, "".join(r["license_plate"].split()), prov))
    return out


def load_det_crops(real_rows=None) -> list[tuple[np.ndarray, str, int]]:
    """ป้ายจริงแบบที่ระบบใช้งานจริง: ให้ตัวตรวจจับป้าย (plate.pt) ตัดจากภาพเต็ม 100 ภาพเอง (ขอบเผื่อ 8%)
    — ต่างจากภาพป้ายที่ตัดไว้ให้ (มีกรอบป้าย/พื้นที่รอบๆ มากกว่า) ใช้ป้ายที่ตัวตรวจจับมั่นใจที่สุดต่อภาพ."""
    import benchmark
    from engine.config import EngineConfig
    from engine.detectors import PlateDetector
    from engine.pipeline import _clip

    cfg = EngineConfig()
    det = PlateDetector(cfg)
    if not det.available:
        return []
    out = []
    for r in benchmark.load_gt(None):
        frame = cv2.imread(str(benchmark.DATA_DIR / r["image"]))
        plates = det.detect(frame)
        if not plates:
            continue
        b = max(plates, key=lambda p: p.conf)
        x1, y1, x2, y2 = _clip(b, frame.shape[1], frame.shape[0], pad=0.08)
        prov = PROVINCE_CLASSES.index(r["province"]) if r["province"] in PROVINCE_CLASSES else -1
        out.append((frame[y1:y2, x1:x2].copy(), "".join(r["license_plate"].split()), prov))
    return out


def load_synth_val(n: int = 1000) -> list[tuple[np.ndarray, str, int]]:
    rng = random.Random(12345)
    np.random.seed(12345)
    fonts = available_fonts(FONT_DIR)
    out = []
    for _ in range(n):
        s = make_sample(rng, fonts)
        out.append((cv2.cvtColor(s.image, cv2.COLOR_RGB2BGR), s.text, s.province))
    return out


# ------------------------------------------------------------------ eval
def char_acc(pred: str, truth: str) -> float:
    prev = list(range(len(truth) + 1))
    for i, a in enumerate(pred, 1):
        cur = [i]
        for j, b in enumerate(truth, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return max(0.0, 1 - prev[-1] / max(len(truth), 1))


def evaluate(model, data, device, bs: int = 256) -> dict:
    import torch

    model.eval()
    text_ok = prov_ok = both = 0
    cacc = 0.0
    with torch.inference_mode():
        for i in range(0, len(data), bs):
            chunk = data[i:i + bs]
            x = torch.from_numpy(np.stack([preprocess(im) for im, _, _ in chunk])).to(device)
            logits, prov = model(x)
            logits = logits.float().cpu().numpy()
            prov = prov.float().argmax(1).cpu().numpy()
            for (im, truth, ptruth), lg, pp in zip(chunk, logits, prov):
                raw, _ = ctc_greedy(lg)
                truth = truth.replace("-", "")
                t_ok, p_ok = raw == truth, int(pp) == ptruth
                text_ok += t_ok
                prov_ok += p_ok
                both += t_ok and p_ok
                cacc += char_acc(raw, truth)
    model.train()
    n = max(len(data), 1)
    return {"plate_text": round(text_ok / n, 4), "province": round(prov_ok / n, 4), "both": round(both / n, 4),
            "char_acc": round(cacc / n, 4)}


# ------------------------------------------------------------------ train
def main() -> None:
    import torch
    from torch import nn

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", type=int, default=60000)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--workers", type=int, default=0, help="0 = อัตโนมัติ")
    ap.add_argument("--device", default=None)
    ap.add_argument("--eval-every", type=int, default=2000)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run", default="platenet", help="ชื่อโฟลเดอร์ผลลัพธ์ใน data/train/ (แยกแต่ละรอบการเทรน)")
    ap.add_argument("--real", action="append", default=[], help="โฟลเดอร์ป้ายจริง (มี labels.csv) ใส่ได้หลายครั้ง")
    ap.add_argument("--real-ratio", type=float, default=0.35, help="สัดส่วนป้ายจริงในแต่ละ batch")
    ap.add_argument("--real-status", default=",".join(REAL_STATUSES),
                    help="ใช้ป้ายจริงสถานะไหนบ้าง (auto=ตัวอ่านตรงกัน, auto2=Typhoon ตัดสิน, human=คนติด)")
    ap.add_argument("--init", default=None, help="เริ่มจากน้ำหนักของ checkpoint นี้ (fine-tune) เช่น engine/models/platenet.pt")
    args = ap.parse_args()

    if not list(FONT_DIR.glob("*.ttf")):  # เครื่องใหม่: ดาวน์โหลดฟอนต์ก่อน
        from training.plate_ocr import fonts

        try:
            fonts.main()
        except SystemExit:
            pass
    global OUT
    OUT = ROOT / "data" / "train" / args.run
    cv2.setNumThreads(1)  # ต้องตั้งก่อนใช้ OpenCV ครั้งแรก (worker ที่ fork ไปจะใช้ค่านี้)
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    workers = args.workers or max(2, min(48, (os.cpu_count() or 4) - 8))  # สร้างป้ายจำลองใช้ CPU หนัก
    torch.set_num_threads(4)
    OUT.mkdir(parents=True, exist_ok=True)

    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    warm = min(1000, args.steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else 0.5 * (1 + math.cos(math.pi * (s - warm) / max(1, args.steps - warm))))
    use_amp = device.startswith("cuda")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    ce = nn.CrossEntropyLoss(label_smoothing=0.05, ignore_index=IGNORE)

    step, best_key = 0, (-1.0, -1.0, -1.0)
    if args.init:
        model.load_state_dict(torch.load(args.init, map_location="cpu", weights_only=True)["model"])
        print(f"เริ่มจากน้ำหนัก {args.init}")
    if args.resume and (OUT / "last.pt").exists():
        ck = torch.load(OUT / "last.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        sched.load_state_dict(ck["sched"])
        step, best_key = ck["step"], tuple(ck["best_key"])
        print(f"เทรนต่อจาก step {step}")

    real, synth_val = load_real(), load_synth_val()
    det_val = load_det_crops()
    st = tuple(args.real_status.split(","))
    real_rows = load_real_rows(args.real, "train", st) if args.real else []
    # โหลดภาพป้ายจริงทั้งหมดครั้งเดียว (ย่อให้ด้านยาว ≤ 256 px) — worker ใช้ร่วมกันผ่าน fork
    real_train = []
    for path, text, prov in real_rows:
        im = cv2.imread(path)
        if im is None:
            continue
        s_ = 256 / max(im.shape[:2])
        if s_ < 1:
            im = cv2.resize(im, (int(im.shape[1] * s_), int(im.shape[0] * s_)), interpolation=cv2.INTER_AREA)
        real_train.append((np.ascontiguousarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)), text, prov))
    if real_train:
        print(f"โหลดป้ายจริง {len(real_train)} ภาพ ({sum(x[0].nbytes for x in real_train) / 1e9:.1f} GB)", flush=True)
    # ชุดทดสอบใช้เฉพาะเฉลยจากคน (human) — เชื่อถือได้ที่สุด
    rp_val = [(cv2.imread(p), t, pv) for p, t, pv in load_real_rows(args.real, "test", ("human",))] if args.real else []
    params = sum(p.numel() for p in model.parameters()) / 1e6
    print(f"device={device} workers={workers} batch={args.batch} steps={args.steps} params={params:.2f}M "
          f"real_val={len(real)} det_val={len(det_val)} synth_val={len(synth_val)} "
          f"real_train={len(real_train)} (ratio {args.real_ratio if real_train else 0}) rp_val={len(rp_val)}")
    loader = torch.utils.data.DataLoader(SynthStream(args.seed + step, real_train, args.real_ratio), batch_size=args.batch, num_workers=workers,
                                         collate_fn=collate, pin_memory=use_amp, persistent_workers=True, worker_init_fn=worker_init,
                                         prefetch_factor=4)
    it = iter(loader)
    t0, seen, loss_ema = time.time(), 0, None
    model.train()
    while step < args.steps:
        imgs, targets, lengths, provs = next(it)
        imgs, targets, provs = imgs.to(device, non_blocking=True), targets.to(device), provs.to(device)
        with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
            logits, prov_logits = model(imgs)
        log_probs = logits.float().log_softmax(2).transpose(0, 1)   # T×B×C
        in_len = torch.full((imgs.shape[0],), log_probs.shape[0], dtype=torch.long)
        loss = ctc(log_probs, targets, in_len, lengths) + 0.5 * ce(prov_logits.float(), provs)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        scaler.step(opt)
        scaler.update()
        sched.step()
        step += 1
        seen += imgs.shape[0]
        loss_ema = loss.item() if loss_ema is None else 0.98 * loss_ema + 0.02 * loss.item()

        if step % 100 == 0:
            rate = seen / (time.time() - t0)
            print(f"step {step:6d}  loss {loss_ema:.3f}  lr {sched.get_last_lr()[0]:.2e}  {rate:.0f} img/s", flush=True)
        if step % args.eval_every == 0 or step == args.steps:
            r, s = evaluate(model, real, device), evaluate(model, synth_val, device)
            dv = evaluate(model, det_val, device) if det_val else r
            rp = evaluate(model, rp_val, device) if rp_val else None
            # เลือกโมเดลจากภาพที่ตัวตรวจจับตัดเอง (แบบใช้งานจริง) ก่อน แล้วค่อยดูภาพที่ตัดไว้ให้
            # เลือกโมเดลจาก: ป้ายจริงที่เฉลยจากคน (ชุดทดสอบใหม่ ใหญ่และเชื่อถือได้ที่สุด) + ภาพที่ตัวตรวจจับตัดเอง + ภาพป้ายที่ตัดไว้
            key = (dv["both"] + r["both"] + (rp["both"] if rp else 0),
                   dv["plate_text"] + r["plate_text"] + (rp["plate_text"] if rp else 0),
                   dv["char_acc"] + r["char_acc"])
            rec = {"step": step, "loss": round(loss_ema, 4), "lr": sched.get_last_lr()[0], "real": r, "det": dv, "rp": rp, "synth": s,
                   "img_per_s": round(seen / (time.time() - t0)), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
            improved = key > best_key
            if improved:
                best_key = key
                torch.save({"model": model.state_dict(), "meta": {"step": step, "real": r, "det": dv, "synth": s,
                                                                  "input": [INPUT_H, INPUT_W]}}, OUT / "best.pt")
            rec["best"] = improved
            with open(OUT / "log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"== step {step}  ป้ายจริง(ตัดให้): เลข {r['plate_text']:.1%} จังหวัด {r['province']:.1%} "
                  f"ทั้งคู่ {r['both']:.1%} | ป้ายจริง(ตัวตรวจจับตัด): เลข {dv['plate_text']:.1%} "
                  f"จังหวัด {dv['province']:.1%} ทั้งคู่ {dv['both']:.1%} | จำลอง: เลข {s['plate_text']:.1%}"
                  + (f" | ป้ายจริงชุดใหม่ {len(rp_val)} ป้าย: เลข {rp['plate_text']:.1%} จังหวัด {rp['province']:.1%}" if rp else "")
                  + ("  ★ best" if improved else ""), flush=True)
            torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                        "step": step, "best_key": list(best_key)}, OUT / "last.pt")
    print(f"เสร็จ — best (ผลรวม 2 ชุดป้ายจริง): ทั้งคู่ {best_key[0]:.2f} เลข {best_key[1]:.2f}  → {OUT / 'best.pt'}")


if __name__ == "__main__":
    main()
