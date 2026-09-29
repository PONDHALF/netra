"""PlateNet — ตัวอ่านป้ายทะเบียนไทยที่เทรนเอง (CRNN + CTC) พร้อมหัวแยกจังหวัด 77 จังหวัด

อินพุต: ภาพป้ายทั้งแผ่น (ที่ตัดจากตัวตรวจจับป้าย) ย่อเป็น 64×192 RGB
เอาต์พุต 2 ส่วนจาก backbone เดียวกัน
  1. เลขทะเบียน: ลำดับตัวอักษร (เลข 0–9 + พยัญชนะ 44 ตัว) ถอดด้วย CTC — อ่านทั้งแถวทีเดียว
     จึงทนต่อป้ายเล็ก/เบลอกว่าการหาทีละตัวอักษร
  2. จังหวัด: จัดหมวดหมู่ 78 คลาส (77 จังหวัด + "ไม่เห็น") — ง่ายกว่าอ่านตัวหนังสือเล็กบรรทัดล่าง

เทรนด้วย training/plate_ocr/train.py
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .postprocess.plate_format import THAI_CONSONANTS
from .postprocess.provinces import PROVINCES

DIGITS = "0123456789"
ALPHABET = DIGITS + THAI_CONSONANTS            # index 0 = CTC blank, ตัวอักษรเริ่มที่ 1
PROVINCE_CLASSES = PROVINCES + ["(ไม่เห็น)"]      # คลาสสุดท้าย = มองไม่เห็นบรรทัดจังหวัด
NO_PROVINCE = len(PROVINCES)
INPUT_H, INPUT_W = 64, 192

_CHAR_TO_IDX = {c: i + 1 for i, c in enumerate(ALPHABET)}
_PLATE_RE = re.compile(rf"^(\d?)([{THAI_CONSONANTS}]{{1,3}})(\d{{1,4}})$")


def encode(text: str) -> list[int]:
    """"1กข 1234" → ดัชนีตัวอักษร (ตัดช่องว่างออก)."""
    return [_CHAR_TO_IDX[c] for c in text if c in _CHAR_TO_IDX]


def format_plate(raw: str) -> tuple[str, bool]:
    """"1กข1234" → ("1กข 1234", ตรงรูปแบบหรือไม่)."""
    m = _PLATE_RE.match(raw)
    if not m:
        return raw, False
    p, letters, num = m.groups()
    return f"{p}{letters} {num}", len(letters) <= 2


def preprocess(bgr: np.ndarray) -> np.ndarray:
    """ภาพป้าย BGR (ขนาดใดก็ได้) → float32 CHW 3×64×192 ช่วง [-1, 1]."""
    import cv2

    img = cv2.resize(bgr, (INPUT_W, INPUT_H), interpolation=cv2.INTER_AREA if bgr.shape[1] > INPUT_W else cv2.INTER_CUBIC)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
    return img.transpose(2, 0, 1)


def build_model():
    import torch
    from torch import nn

    def block(cin, cout, pool):
        layers = [nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True)]
        if pool:
            layers.append(nn.MaxPool2d(pool))
        return layers

    class PlateNet(nn.Module):
        def __init__(self, n_chars: int = len(ALPHABET) + 1, n_prov: int = len(PROVINCE_CLASSES)):
            super().__init__()
            self.backbone = nn.Sequential(
                *block(3, 32, 2),              # 32×96
                *block(32, 64, 2),             # 16×48
                *block(64, 128, None),
                *block(128, 128, (2, 1)),      # 8×48
                *block(128, 256, None),
                *block(256, 256, (2, 1)),      # 4×48
                nn.Dropout2d(0.1),
            )
            # ยุบความสูง 4 → 1 ด้วย conv ที่เรียนรู้ได้ (ให้โมเดลเลือกเองว่าจะดูแถวบนหรือล่าง)
            self.collapse = nn.Sequential(nn.Conv2d(256, 256, (4, 1), bias=False), nn.BatchNorm2d(256), nn.ReLU(inplace=True))
            self.rnn = nn.LSTM(256, 128, num_layers=2, bidirectional=True, batch_first=True, dropout=0.1)
            self.ctc_head = nn.Linear(256, n_chars)
            self.prov_head = nn.Sequential(nn.Linear(512, 256), nn.ReLU(inplace=True), nn.Dropout(0.2), nn.Linear(256, n_prov))

        def forward(self, x):
            f = self.backbone(x)                                   # B×256×4×48
            seq = self.collapse(f).squeeze(2).transpose(1, 2)      # B×48×256
            seq, _ = self.rnn(seq)
            logits = self.ctc_head(seq)                            # B×48×C
            pooled = torch.cat([f.mean((2, 3)), f.amax((2, 3))], 1)
            return logits, self.prov_head(pooled)

    return PlateNet()


def ctc_greedy(logits: np.ndarray) -> tuple[str, float]:
    """logits T×C (ของ 1 ภาพ) → (ข้อความ, ความมั่นใจเฉลี่ยของตัวที่ถอดได้)."""
    probs = np.exp(logits - logits.max(1, keepdims=True))
    probs /= probs.sum(1, keepdims=True)
    best = probs.argmax(1)
    out, confs, prev = [], [], 0
    for t, k in enumerate(best):
        if k != prev and k != 0:
            out.append(ALPHABET[k - 1])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(out), (float(np.mean(confs)) if confs else 0.0)


@dataclass
class PlateNetResult:
    text: str | None
    valid: bool
    conf: float
    province: str | None
    province_conf: float
    raw: str


class PlateNetReader:
    """โหลด checkpoint (engine/models/platenet.pt) แล้วอ่านภาพป้าย."""

    def __init__(self, path: str, device: str = "cpu"):
        import torch

        ckpt = torch.load(path, map_location="cpu", weights_only=True)
        self.model = build_model()
        self.model.load_state_dict(ckpt["model"])
        self.device = device
        self.model.to(device).eval()
        self.torch = torch

    def read(self, bgr: np.ndarray) -> PlateNetResult:
        return self.read_batch([bgr])[0]

    def read_batch(self, images: list[np.ndarray]) -> list[PlateNetResult]:
        torch = self.torch
        x = torch.from_numpy(np.stack([preprocess(im) for im in images])).to(self.device)
        with torch.inference_mode():
            logits, prov = self.model(x)
        logits = logits.float().cpu().numpy()
        prov = torch.softmax(prov.float(), 1).cpu().numpy()
        out = []
        for lg, pv in zip(logits, prov):
            raw, conf = ctc_greedy(lg)
            text, valid = format_plate(raw)
            k = int(pv.argmax())
            province = PROVINCE_CLASSES[k] if k != NO_PROVINCE else None
            out.append(PlateNetResult(text or None, valid, round(conf if valid else conf * 0.6, 4), province,
                                      round(float(pv[k]), 4), raw))
        return out
