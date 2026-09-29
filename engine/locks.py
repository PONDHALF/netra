"""กันการเรียกโมเดลพร้อมกันจากหลาย thread (งานวิดีโอ + กล้องสดหลายตัว)

- CUDA: lock แยกต่อโมเดล (predictor ของ ultralytics ไม่ thread-safe) — โมเดลต่างตัวรันซ้อนกันได้
- MPS (Apple): GPU ใช้จากหลาย thread พร้อมกันไม่ได้ (crash "command encoder is already encoding")
  จึงใช้ lock เดียวร่วมกันทุกโมเดล
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_GLOBAL = threading.RLock()
_serialize_all = False


def configure(device: str) -> None:
    global _serialize_all
    _serialize_all = device == "mps"


@contextmanager
def guard(local_lock: threading.Lock | None = None):
    lock = _GLOBAL if _serialize_all else local_lock
    if lock is None:
        yield
        return
    with lock:
        yield
