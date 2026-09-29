"""กันการเรียกโมเดลพร้อมกันจากหลาย thread (งานวิดีโอ + กล้องสดหลายตัว)

- CUDA: lock แยกต่อโมเดล (predictor ของ ultralytics ไม่ thread-safe) — โมเดลต่างตัวรันซ้อนกันได้
- MPS (Apple): GPU ใช้จากหลาย thread พร้อมกันไม่ได้ (crash "command encoder is already encoding")
  จึงใช้ lock เดียวร่วมกันทุกโมเดล
- การเรียกครั้งแรกของโมเดล YOLO (โหลด TensorRT engine) ต้องรันคนเดียว: ultralytics อัด CUDA graph ตอนโหลด
  ถ้า thread อื่นใช้ GPU พร้อมกันจะพัง (cudaErrorStreamCaptureInvalidated) → guard(exclusive=True) รอให้งานอื่นหยุดก่อน
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_GLOBAL = threading.RLock()
_serialize_all = False


class _Gate:
    """shared/exclusive: การเรียกปกติเข้าได้พร้อมกัน (shared) — exclusive รอจนไม่มีใครใช้ แล้วกันไม่ให้ใครเข้า."""

    def __init__(self):
        self._cv = threading.Condition()
        self._active = 0
        self._exclusive = False
        self._waiting = 0
        self._local = threading.local()

    @contextmanager
    def shared(self):
        depth = getattr(self._local, "depth", 0)
        if depth == 0:  # เรียกซ้อนใน thread เดียวกัน (เช่น OCR ภายใน track) ไม่ต้องรอซ้ำ
            with self._cv:
                self._cv.wait_for(lambda: not self._exclusive and not self._waiting)
                self._active += 1
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth = depth
            if depth == 0:
                with self._cv:
                    self._active -= 1
                    self._cv.notify_all()

    @contextmanager
    def exclusive(self):
        if getattr(self._local, "depth", 0):  # อยู่ใน shared แล้ว — ยกระดับไม่ได้ (deadlock) ใช้ต่อไปเลย
            yield
            return
        with self._cv:
            self._waiting += 1
            self._cv.wait_for(lambda: not self._exclusive and self._active == 0)
            self._waiting -= 1
            self._exclusive = True
        self._local.depth = 1
        try:
            yield
        finally:
            self._local.depth = 0
            with self._cv:
                self._exclusive = False
                self._cv.notify_all()


_GATE = _Gate()


def configure(device: str) -> None:
    global _serialize_all
    _serialize_all = device == "mps"


@contextmanager
def guard(local_lock: threading.Lock | None = None, exclusive: bool = False):
    lock = _GLOBAL if _serialize_all else local_lock
    with (_GATE.exclusive() if exclusive else _GATE.shared()):
        if lock is None:
            yield
            return
        with lock:
            yield


def needs_setup(model) -> bool:
    """โมเดล ultralytics ที่ยังไม่เคยเรียก (ครั้งแรกจะโหลด engine + อัด CUDA graph)."""
    p = getattr(model, "predictor", None)
    return p is None or getattr(p, "model", None) is None
