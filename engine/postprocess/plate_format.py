"""ตรวจรูปแบบป้ายทะเบียนไทย รวมข้อความจาก OCR และ vote ข้ามหลายเฟรม.

รูปแบบที่รองรับ
- รถยนต์:      "กข 1234", "1กข 1234"  (บรรทัดบน) + จังหวัด (บรรทัดล่าง)
- จักรยานยนต์: "1กข" + จังหวัด + "123"  (3 บรรทัด)
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .provinces import match_province

THAI_CONSONANTS = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
# ตัวอักษรละตินที่ OCR มักสับสนกับตัวเลข
_LATIN_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                                 "i": "1", "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "g": "9"})

_PLATE_RE = re.compile(rf"(\d?)([{THAI_CONSONANTS}]{{1,3}})(\d{{1,4}})")
_FULL_RE = re.compile(rf"^\d?[{THAI_CONSONANTS}]{{1,3}} \d{{1,4}}$")


@dataclass
class OcrToken:
    text: str
    conf: float
    y: float = 0.0  # จุดกึ่งกลางแนวตั้ง (ใช้เรียงบรรทัด)
    x: float = 0.0
    h: float = 0.0  # ความสูงของกรอบข้อความ


@dataclass
class PlateReading:
    text: str | None = None          # "1กข 1234"
    province: str | None = None
    conf: float = 0.0                # 0-1
    raw: str = ""
    valid: bool = False               # ตรงรูปแบบป้ายไทยทั้งป้าย
    extras: dict = field(default_factory=dict)


def _normalize(s: str) -> str:
    s = s.strip().translate(_THAI_DIGITS).translate(_LATIN_TO_DIGIT)
    # เลข 1 นำหน้าหมวดอักษร มักถูกอ่านเป็น "ไ" (เช่น "ไกข" → "1กข")
    if len(s) >= 2 and s[0] == "ไ" and s[1] in THAI_CONSONANTS:
        s = "1" + s[1:]
    # เก็บเฉพาะพยัญชนะไทยและตัวเลข (ตัดสระ วรรณยุกต์ จุด ขีด ที่มักเป็นสัญญาณรบกวน)
    return "".join(ch for ch in s if ch.isdigit() or ch in THAI_CONSONANTS)


def _reading_order(tokens: list[OcrToken]) -> list[OcrToken]:
    """จัดกลุ่ม token เป็นบรรทัด (y ใกล้กัน) แล้วเรียงซ้าย→ขวาในแต่ละบรรทัด."""
    lines: list[list[OcrToken]] = []
    for t in sorted(tokens, key=lambda t: t.y):
        if lines:
            ref = lines[-1]
            ly = sum(x.y for x in ref) / len(ref)
            lh = max(max(x.h for x in ref), t.h, 12.0)
            if abs(t.y - ly) < lh * 0.5:
                ref.append(t)
                continue
        lines.append([t])
    return [t for line in lines for t in sorted(line, key=lambda t: t.x)]


def parse_tokens(tokens: list[OcrToken]) -> PlateReading:
    """รวม token จาก OCR หนึ่งภาพให้เป็นเลขทะเบียน + จังหวัด."""
    if not tokens:
        return PlateReading()
    tokens = _reading_order(tokens)
    raw = " | ".join(t.text for t in tokens)

    province, prov_conf, prov_idx = None, 0.0, -1
    for i, t in enumerate(tokens):
        if sum(ch.isdigit() for ch in t.text.translate(_THAI_DIGITS)) > 0:
            continue
        name, score = match_province(t.text)
        if name and score * t.conf > prov_conf:
            province, prov_conf, prov_idx = name, score * t.conf, i

    rest = [t for i, t in enumerate(tokens) if i != prov_idx]
    norms = [_normalize(t.text) for t in rest]
    m = _PLATE_RE.search("".join(norms))
    if not m:
        # หมวดอักษรและตัวเลขอาจแยกเป็นคนละกล่อง/สลับลำดับ (เช่น ป้ายจักรยานยนต์)
        letters = "".join(n for n in norms if any(c in THAI_CONSONANTS for c in n))
        digits = "".join(n for n in norms if n.isdigit())
        m = _PLATE_RE.search(letters + digits)
    if not m:
        return PlateReading(province=province, conf=0.0, raw=raw)

    prefix, letters, number = m.groups()
    text = f"{prefix}{letters} {number}"
    used = [t for t in rest if _normalize(t.text)]
    conf = sum(t.conf for t in used) / max(len(used), 1)
    valid = bool(_FULL_RE.match(text)) and len(letters) <= 2
    if not valid:
        conf *= 0.6
    if province is None:
        conf *= 0.9
    return PlateReading(text=text, province=province, conf=round(conf, 4), raw=raw, valid=valid)


def vote(readings: list[PlateReading]) -> PlateReading:
    """เลือกผลที่ได้คะแนนรวมสูงสุดข้ามหลายเฟรม (vote หลายเฟรม)."""
    text_score: dict[str, float] = defaultdict(float)
    prov_score: dict[str, float] = defaultdict(float)
    best_by_text: dict[str, PlateReading] = {}
    for r in readings:
        if r.text:
            text_score[r.text] += r.conf + (0.2 if r.valid else 0.0)
            if r.text not in best_by_text or r.conf > best_by_text[r.text].conf:
                best_by_text[r.text] = r
        if r.province:
            prov_score[r.province] += max(r.conf, 0.3)
    if not text_score:
        prov = max(prov_score, key=prov_score.get) if prov_score else None
        return PlateReading(province=prov, raw=" / ".join(r.raw for r in readings if r.raw))

    text = max(text_score, key=text_score.get)
    base = best_by_text[text]
    agree = sum(1 for r in readings if r.text == text)
    # ยิ่งหลายเฟรมอ่านได้ตรงกัน ยิ่งมั่นใจ
    conf = min(1.0, base.conf * (1 + 0.1 * (agree - 1)))
    prov = max(prov_score, key=prov_score.get) if prov_score else None
    return PlateReading(text=text, province=prov, conf=round(conf, 4), raw=base.raw, valid=base.valid,
                        extras={"votes": agree, "frames": len(readings)})
