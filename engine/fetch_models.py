"""ดาวน์โหลดโมเดลป้ายทะเบียนไทยจาก Hugging Face มาไว้ที่ engine/models/

    python -m engine.fetch_models          # ข้ามไฟล์ที่มีอยู่แล้วและ hash ถูกต้อง
    python -m engine.fetch_models --force  # โหลดใหม่ทั้งหมด
    python -m engine.fetch_models --typhoon  # โหลด Typhoon OCR 3B ด้วย (~7.5 GB, safetensors)

ความปลอดภัย: ไฟล์ .pt เป็น pickle ซึ่งรันโค้ดได้ตอนโหลด จึง
  1) ตรึง revision และตรวจ SHA-256 ให้ตรงกับไฟล์ที่ทดสอบแล้ว
  2) สแกน pickle แบบ static (ไม่ unpickle) ว่าอ้างถึงเฉพาะ module ที่อนุญาต
"""
from __future__ import annotations

import argparse
import hashlib
import io
import pickletools
import sys
import socket
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"


@dataclass(frozen=True)
class ModelSpec:
    target: str
    repo: str
    revision: str
    filename: str
    sha256: str
    license: str
    note: str
    url_override: str | None = None

    @property
    def url(self) -> str:
        return self.url_override or f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.filename}"


MODELS = [
    ModelSpec(
        target="yolo11s.pt",
        repo="ultralytics/assets",
        revision="v8.3.0",
        filename="yolo11s.pt",
        sha256="85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5",
        license="AGPL-3.0",
        note="ตรวจจับรถ (YOLO11s, COCO)",
        url_override="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt",
    ),
    ModelSpec(
        target="plate.pt",
        repo="tanawichsingpae/thai-license-plate-detector",
        revision="f53e5dbc7011203a834ab5c054a55546b4090847",
        filename="best.pt",
        sha256="e00e9d1439bff3ba7e159b7c0d018fcebcda5bd590ed62eb0eab766d3e43aaa6",
        license="MIT",
        note="ตรวจจับป้าย (YOLOv8s, 1 class)",
    ),
    ModelSpec(
        target="plate_ocr.pt",
        repo="tanawichsingpae/thai-license-plate-ocr",
        revision="e812cfafbd73862610a2514f19db23eeb732727d",
        filename="best.pt",
        sha256="ac025adacb655e8651af066b58738fd67edc9a422e781e6b5280a207dde3af6b",
        license="MIT",
        note="อ่านป้ายรายตัวอักษร (YOLOv8s, 124 class: เลข/พยัญชนะ/จังหวัด)",
    ),
]

ALLOWED_GLOBAL_PREFIXES = ("torch.", "ultralytics.", "collections.OrderedDict", "__builtin__.set", "builtins.set")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_pickle(path: Path) -> list[str]:
    """คืนรายชื่อ global ที่ไม่อยู่ใน allow-list (ว่าง = ปลอดภัย)."""
    bad: set[str] = set()
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".pkl"):
                continue
            strings: list[str] = []
            for op, arg, _ in pickletools.genops(io.BytesIO(z.read(name))):
                if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE"):
                    strings = (strings + [arg])[-2:]
                elif op.name == "GLOBAL":
                    g = arg.replace(" ", ".")
                    if not g.startswith(ALLOWED_GLOBAL_PREFIXES):
                        bad.add(g)
                elif op.name == "STACK_GLOBAL":
                    g = ".".join(strings)
                    if not g.startswith(ALLOWED_GLOBAL_PREFIXES):
                        bad.add(g)
    return sorted(bad)


def fetch(spec: ModelSpec, force: bool = False) -> Path:
    socket.setdefaulttimeout(60)  # กันค้างถ้าเครือข่ายไม่ตอบ
    dest = MODELS_DIR / spec.target
    if dest.exists() and not force:
        if sha256(dest) == spec.sha256:
            print(f"✓ {spec.target} มีอยู่แล้ว")
            return dest
        print(f"! {spec.target} hash ไม่ตรง — โหลดใหม่")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    print(f"↓ {spec.target} ← {spec.repo} ({spec.note}, {spec.license})")
    digest = ""
    for attempt in range(1, 4):  # เครือข่ายหลุดกลางทาง → ลองใหม่ (ไฟล์ไม่ครบจะ hash ไม่ตรง)
        try:
            urllib.request.urlretrieve(spec.url, tmp)
            digest = sha256(tmp)
            if digest == spec.sha256:
                break
            print(f"  ! {spec.target}: hash ไม่ตรง (ครั้งที่ {attempt}) — ลองใหม่")
        except OSError as e:
            print(f"  ! {spec.target}: ดาวน์โหลดไม่สำเร็จ (ครั้งที่ {attempt}): {e}")
    if digest != spec.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{spec.target}: ดาวน์โหลดไม่ครบหรือ SHA-256 ไม่ตรง ({digest or 'ไม่มีไฟล์'})")
    bad = scan_pickle(tmp)
    if bad:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{spec.target}: พบการอ้างถึง module ที่ไม่อนุญาต {bad}")
    tmp.replace(dest)
    print(f"✓ {spec.target} ติดตั้งแล้ว")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--typhoon", action="store_true", help="ดาวน์โหลด Typhoon OCR 3B ไว้ล่วงหน้า")
    args = ap.parse_args()
    failed = False
    for spec in MODELS:
        try:
            fetch(spec, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"✗ {spec.target}: {e}", file=sys.stderr)
            failed = True
    if args.typhoon:
        try:
            from huggingface_hub import snapshot_download

            from .typhoon import REPO, REVISION

            # safetensors ไม่ใช่ pickle — ไม่รันโค้ดตอนโหลด (ไม่ต้องสแกน)
            print(f"↓ Typhoon OCR 3B ← {REPO}@{REVISION[:8]} (~7.5 GB, Apache-2.0)")
            snapshot_download(REPO, revision=REVISION, allow_patterns=["*.json", "*.safetensors", "*.txt"])
            print("✓ Typhoon OCR 3B พร้อมใช้ (เปิดด้วย NETRA_TYPHOON=1)")
        except Exception as e:  # noqa: BLE001
            print(f"✗ Typhoon OCR 3B: {e}", file=sys.stderr)
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
