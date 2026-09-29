"""ประมวลผลภาพสดจากกล้องทีละเฟรม (real-time) — ใช้ตรรกะเดียวกับ pipeline วิดีโอ

ต่างจากวิดีโอ 3 อย่าง
  1. ไม่มีจุดจบ: รถที่ออกจากภาพจะถูกสรุปผล (vote OCR) ใน thread แยก เพื่อไม่ให้ภาพสดกระตุก
  2. แสดงเลขทะเบียนชั่วคราวบนภาพสดระหว่างรถยังอยู่ในภาพ (อ่านด้วยโมเดลรายตัวอักษรซึ่งเร็ว)
  3. tracker แยกต่อกล้อง — โมเดลตรวจจับป้าย/อ่านป้ายใช้ร่วมกับ Engine (มี lock กันชนกันแล้ว)
"""
from __future__ import annotations

import logging
import time

import cv2
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np

from .detectors import VehicleTracker, assign_plates
from .draw import TYPE_TH, draw_frame
from .pipeline import Engine, VehicleEvent, _clip, _Track

log = logging.getLogger("netra.stream")

LIVE_READ_EVERY = 4        # อ่านเลขทะเบียนชั่วคราวทุกๆ N เฟรมต่อคัน
LIVE_MIN_PLATE_PX = 40     # ป้ายแคบกว่านี้ไม่ต้องอ่านสด (อ่านไม่ได้อยู่แล้ว)


class StreamSession:
    def __init__(self, engine: Engine, out_dir: Path, fps: float, tag: str,
                 on_event: Callable[[VehicleEvent, float], None] | None = None, out_width: int = 1280):
        """fps = อัตราเฟรมที่ประมวลผลจริง (ใช้แปลงจำนวนเฟรมเป็นเวลา)
        tag = คำนำหน้า track key ให้ชื่อไฟล์ภาพไม่ซ้ำข้ามการเริ่มกล้องแต่ละครั้ง
        on_event(event, unix_ts) ถูกเรียกจาก thread สรุปผล เมื่อรถแต่ละคันออกจากภาพ"""
        self.engine, self.cfg = engine, engine.cfg
        self.tracker = VehicleTracker(self.cfg)
        self.fps, self.tag, self.on_event = fps, tag, on_event
        self.out_dir = Path(out_dir)
        (self.out_dir / "events").mkdir(parents=True, exist_ok=True)
        self.tracks: dict[int, _Track] = {}
        self.generation: Counter = Counter()
        self.frame_time: dict[int, float] = {}
        self.recent: dict[str, float] = {}
        self.dups: dict[str, str] = {}
        self.idx = -1
        self.lost_frames = max(int(self.cfg.lost_seconds * fps), 32)
        self._finalizer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="netra-finalize")
        self.out_width = out_width
        self.timing: dict[str, float] = {}  # ms ต่อเฟรม (ค่าเฉลี่ยเคลื่อนที่) แยกตามขั้น — ใช้หาคอขวด

    def _tick(self, name: str, t0: float) -> float:
        now = time.perf_counter()
        ms = (now - t0) * 1000
        prev = self.timing.get(name)
        self.timing[name] = round(ms if prev is None else prev * 0.9 + ms * 0.1, 1)
        return now

    def process(self, frame: np.ndarray) -> np.ndarray:
        """ประมวลผล 1 เฟรม แล้วคืนภาพที่วาดกรอบแล้ว (สำเนา)."""
        self.idx += 1
        self.frame_time[self.idx] = time.time()
        H, W = frame.shape[:2]
        engine = self.engine

        t = time.perf_counter()
        vehicles = self.tracker.track(frame)
        t = self._tick("vehicles", t)
        # หาป้ายเฉพาะเมื่อมีรถคันใหญ่พอจะอ่านป้ายได้ (เฟรมที่มีแต่รถไกลๆ ไม่ต้องเสีย ~25–40 ms)
        big_enough = any((b.x2 - b.x1) >= self.cfg.min_vehicle_frac * W for _, _, b in vehicles)
        plates = engine.plates.detect(frame) if engine.plates.available and big_enough else []
        t = self._tick("plates", t)
        items = []
        for v in assign_plates(vehicles, plates):
            tr = self.tracks.get(v.track_id)
            if tr is None:
                self.generation[v.track_id] += 1
                tr = _Track(key=f"{self.tag}-{v.track_id}-{self.generation[v.track_id]}", track_id=v.track_id,
                            first_frame=self.idx, last_frame=self.idx)
                self.tracks[v.track_id] = tr
            tr.last_frame = self.idx
            tr.hits += 1
            tr.max_conf = max(tr.max_conf, v.box.conf)
            tr.max_width = max(tr.max_width, (v.box.x2 - v.box.x1) / W)
            tr.cls_votes[v.cls] += v.box.conf
            engine._consider(tr, v, frame, self.idx, W, H)
            self._live_read(tr, v, frame, W, H)
            label = tr.live_text or TYPE_TH.get(v.cls, v.cls)
            items.append({"box": v.box.as_int(), "plate": v.plate.as_int() if v.plate else None,
                          "cls": v.cls, "label": label})

        t = self._tick("track+ocr", t)
        for tid in [k for k, tr in self.tracks.items() if self.idx - tr.last_frame > self.lost_frames]:
            self._finalizer.submit(self._finalize, self.tracks.pop(tid))
        if self.idx % 500 == 0:  # ทิ้งเวลาของเฟรมเก่า (เก็บไว้ ~10 นาที)
            cutoff = self.idx - int(self.fps * 600)
            for k in [k for k in self.frame_time if k < cutoff]:
                del self.frame_time[k]
        # ย่อภาพก่อนวาด (ภาพสดไม่ต้องใช้ความละเอียดเต็ม) — วาด 1080p ด้วย PIL ช้ากว่ามาก
        s = min(1.0, self.out_width / W)
        if s < 1.0:
            view = cv2.resize(frame, (int(W * s), int(H * s)), interpolation=cv2.INTER_LINEAR)
            for it in items:
                it["box"] = tuple(int(c * s) for c in it["box"])
                if it["plate"]:
                    it["plate"] = tuple(int(c * s) for c in it["plate"])
        else:
            view = frame.copy()
        out = draw_frame(view, items, self.cfg.font_path)
        self._tick("draw", t)
        return out

    def _live_read(self, tr: _Track, v, frame: np.ndarray, W: int, H: int) -> None:
        """อ่านเลขทะเบียนชั่วคราวไว้แสดงบนภาพสด — ใช้เฉพาะโมเดลรายตัวอักษร (เร็ว ~10 ms บน GPU)."""
        reader = self.engine.reader.char
        if reader is None or v.plate is None or self.idx - tr.live_idx < LIVE_READ_EVERY:
            return
        x1, y1, x2, y2 = _clip(v.plate, W, H, pad=0.08)
        if x2 - x1 < LIVE_MIN_PLATE_PX:
            return
        tr.live_idx = self.idx
        try:
            r = reader.read(frame[y1:y2, x1:x2])
        except Exception:  # noqa: BLE001
            return
        if r.valid and r.conf >= 0.4:
            tr.live_text = r.text

    def _finalize(self, tr: _Track) -> None:
        try:
            ev = self.engine._finalize(tr, self.fps, self.out_dir, self.recent, self.dups)
        except Exception:  # noqa: BLE001
            log.exception("สรุปผลรถ %s ไม่สำเร็จ", tr.key)
            return
        if ev is None or self.on_event is None:
            return
        best_idx = round(ev.video_offset_sec * self.fps)
        ts = self.frame_time.get(best_idx) or self.frame_time.get(tr.last_frame) or time.time()
        try:
            self.on_event(ev, ts)
        except Exception:  # noqa: BLE001
            log.exception("บันทึก event ไม่สำเร็จ")

    def close(self) -> None:
        """สรุปผลรถที่ยังค้างอยู่ในภาพ แล้วรอให้เสร็จ."""
        for tr in list(self.tracks.values()):
            self._finalizer.submit(self._finalize, tr)
        self.tracks.clear()
        self._finalizer.shutdown(wait=True)
