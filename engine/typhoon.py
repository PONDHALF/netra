"""Typhoon OCR 3B (typhoon-ai/typhoon-ocr-3b) — ตัวอ่านเสริมสำหรับจังหวัดและป้ายที่อ่านไม่ครบ

เปิดด้วย NETRA_TYPHOON=1 (ปิดเป็นค่าเริ่มต้น: ใช้แรม ~7.5 GB และ ~2 วินาทีต่อป้ายบน Apple M-series)
เรียกครั้งเดียวต่อรถหนึ่งคัน บนเฟรมที่ชัดที่สุด

ผลทดสอบบน thai-parking-100 (ภาพป้ายที่ตัดแล้ว 100 ภาพ):
  char-OCR อย่างเดียว           เลข 70%  จังหวัด 48%  ถูกทั้งคู่ 36%
  char-OCR + Typhoon (วิธีนี้)   เลข 71%  จังหวัด 74%  ถูกทั้งคู่ 56%
"""
from __future__ import annotations

import json
import logging
import re

import cv2
import numpy as np

from .postprocess import OcrToken, PlateReading, parse_tokens

log = logging.getLogger("netra.engine")

REPO = "typhoon-ai/typhoon-ocr-3b"
REVISION = "f5103a5450e4a6a6331e5fac6911aaff3d827acf"


def prompt(base_text: str = "") -> str:
    # prompt "default" ตามการ์ดโมเดล — โมเดลถูกเทรนมากับ prompt นี้เท่านั้น ห้ามแก้ข้อความ
    return ("Below is an image of a document page along with its dimensions. "
            "Simply return the markdown representation of this document, presenting tables in markdown format as they naturally appear.\n"
            "If the document contains images, use a placeholder like dummy.png for each image.\n"
            "Your final output must be in JSON format with a single key `natural_text` containing the response.\n"
            f"RAW_TEXT_START\n{base_text}\nRAW_TEXT_END")


def to_reading(raw: str) -> PlateReading:
    """ข้อความจาก Typhoon (JSON/markdown) → แยกบรรทัด → parse รูปแบบป้ายไทยแบบเดียวกับตัวอ่านอื่น."""
    text = raw
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            text = json.loads(m.group(0)).get("natural_text", raw)
        except json.JSONDecodeError:
            pass
    lines = [re.sub(r"[#*`|>_\-]", " ", ln).strip() for ln in str(text).splitlines()]
    tokens = [OcrToken(ln, 1.0, y=i * 40.0, x=0.0, h=30.0) for i, ln in enumerate(ln for ln in lines if ln)]
    reading = parse_tokens(tokens)
    reading.raw = str(text).replace("\n", " | ")
    reading.extras = {"source": "typhoon"}
    return reading


class TyphoonOCR:
    def __init__(self, device: str, min_height: int = 256):
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        self.torch, self.device, self.min_height = torch, device, min_height
        if device == "cpu":
            dtype = torch.float32
        elif device.startswith("cuda") and not torch.cuda.is_bf16_supported():
            dtype = torch.float16  # การ์ดรุ่นก่อน RTX 30 ไม่รองรับ bf16
        else:
            dtype = torch.bfloat16
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            REPO, revision=REVISION, torch_dtype=dtype).to(device).eval()
        self.processor = AutoProcessor.from_pretrained(REPO, revision=REVISION)

    def raw(self, bgr: np.ndarray) -> str:
        from PIL import Image

        if bgr.shape[0] < self.min_height:
            s = self.min_height / bgr.shape[0]
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt()}, {"type": "image"}]}]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=[img], return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=96, do_sample=False, repetition_penalty=1.2)
        return self.processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]

    def read(self, bgr: np.ndarray) -> PlateReading:
        if bgr is None or bgr.size == 0:
            return PlateReading()
        return to_reading(self.raw(bgr))


def _digits(text: str | None) -> int:
    return sum(ch.isdigit() for ch in text or "")


def is_available() -> bool:
    """ติดตั้ง transformers แล้ว และดาวน์โหลดโมเดลไว้ในเครื่องแล้ว (ไม่โหลดโมเดลจริง)."""
    try:
        import transformers  # noqa: F401
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(REPO, "config.json", revision=REVISION), str)
    except Exception:  # noqa: BLE001
        return False


def merge(base: PlateReading, ty: PlateReading) -> PlateReading:
    """เลขทะเบียน: ใช้ของ Typhoon เมื่ออ่านได้ครบรูปแบบ และตัวอ่านหลักไม่ครบ/ไม่มั่นใจ/ได้ตัวเลขน้อยกว่า
    (ป้ายเล็กริมถนน โมเดลรายตัวอักษรมักได้เศษอย่าง "ธง 7" ซึ่งดูครบรูปแบบแต่ขาดตัวเลข)
    จังหวัด: ใช้ของ Typhoon ก่อน

    เชื่อจังหวัดจาก Typhoon เฉพาะเมื่ออ่านเลขทะเบียนได้ครบรูปแบบด้วย: ถ้าป้ายเล็ก/เบลอจนอ่านเลขไม่ได้
    Typhoon มักตอบชื่อจังหวัดที่ไม่เกี่ยวข้องมา (เช่น ระนอง, ตราด) ซึ่งเป็นการเดา
    """
    use_ty = ty.valid and (not base.valid or base.conf < 0.5 or _digits(ty.text) > _digits(base.text))
    if use_ty:
        base.text, base.valid = ty.text, True
        base.conf = max(base.conf, 0.5)
        base.extras["source"] = "typhoon"
    if ty.province and ty.valid:
        base.province = ty.province
        base.extras["province_source"] = "typhoon"
    base.raw = f"{base.raw} / typhoon: {ty.raw}" if ty.raw else base.raw
    return base
