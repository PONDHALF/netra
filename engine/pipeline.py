"""Pipeline หลัก: อ่านวิดีโอ → ตรวจจับ + ติดตามรถ → หาป้าย → เลือกเฟรมที่ดีที่สุด → OCR → บันทึก

ขั้นตอน
  1. analyzing  AI ประมวลผล ส่ง event ออกทันทีที่รถแต่ละคันออกจากภาพ
  2. refining   (ถ้าเปิด Typhoon) อ่านป้ายซ้ำด้วย Typhoon OCR 3B ทีละคัน แล้วส่ง event ที่อัปเดตออกไป
                — ทำหลังวิเคราะห์เสร็จ และคืนหน่วยความจำทันทีหลังใช้ เพื่อไม่ให้แย่งแรมกับ YOLO
  3. rendering  วาดกรอบ + เลขทะเบียนลงวิดีโอ แล้ว encode เป็น H.264 ให้เล่นบนเว็บได้
"""
from __future__ import annotations

import gc
import logging
import math
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import locks
from .config import EngineConfig
from .detectors import Box, PlateDetector, VehicleTracker, assign_plates
from .draw import TYPE_TH, draw_frame
from .ocr import PlateReader, sharpness
from .postprocess import vote

log = logging.getLogger("netra.engine")


class Cancelled(Exception):
    pass


@dataclass
class VehicleEvent:
    track_id: int
    vehicle_type: str
    vehicle_conf: float
    video_offset_sec: float        # เวลาของเฟรมที่ชัดที่สุด (ใช้กระโดดในวิดีโอ)
    first_seen_sec: float
    last_seen_sec: float
    plate_text: str | None
    plate_province: str | None
    plate_conf: float
    plate_valid: bool
    car_img: str                   # path สัมพัทธ์กับ out_dir
    plate_img: str | None
    ocr_raw: str = ""
    votes: int = 0
    ocr_engine: str = ""           # ตัวอ่านที่ให้เลขทะเบียน: char-ocr | easyocr | typhoon
    key: str = ""                  # track key (ใช้อ้างถึงตอนอัปเดตผล)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Progress:
    progress: float                # 0-1
    stage: str                     # "analyzing" | "refining" | "rendering" | "done"
    frame: int
    total_frames: int
    fps: float                     # ความเร็วประมวลผล (เฟรม/วินาที)
    eta_sec: float | None
    events: int


@dataclass
class _Candidate:
    score: float
    frame_idx: int
    car: np.ndarray
    plate: np.ndarray | None
    plate_box: tuple[int, int, int, int] | None  # พิกัดใน car crop


@dataclass
class _Track:
    key: str
    track_id: int
    first_frame: int
    last_frame: int
    hits: int = 0
    max_conf: float = 0.0
    max_width: float = 0.0
    live_text: str | None = None      # เลขทะเบียนชั่วคราวที่แสดงบนภาพสด (อ่านระหว่างรถยังอยู่ในภาพ)
    live_idx: int = -1000
    cls_votes: Counter = field(default_factory=Counter)
    candidates: list[_Candidate] = field(default_factory=list)


def _clip(b: Box, w: int, h: int, pad: float = 0.0) -> tuple[int, int, int, int]:
    pw, ph = (b.x2 - b.x1) * pad, (b.y2 - b.y1) * pad
    return (max(0, int(b.x1 - pw)), max(0, int(b.y1 - ph)), min(w, int(b.x2 + pw)), min(h, int(b.y2 + ph)))


class Engine:
    """โหลดโมเดลครั้งเดียว แล้วใช้ประมวลผลได้หลายวิดีโอ."""

    def __init__(self, cfg: EngineConfig | None = None):
        self.cfg = cfg or EngineConfig()
        locks.configure(self.cfg.device)
        from .config import limit_threads

        log.info("threads: %d", limit_threads())
        t = time.time()
        self.tracker = VehicleTracker(self.cfg)
        self.plates = PlateDetector(self.cfg)
        self.reader = PlateReader(self.cfg.device, self.cfg.ocr_gpu, char_model=self.cfg.plate_ocr_model)
        self._typhoon = None
        self._typhoon_lock = threading.Lock()   # โหลด/ใช้ Typhoon ได้ทีละงาน (งานวิดีโอ + กล้องสด)
        self.finalize_lock = threading.Lock()   # _finalize ใช้ OCR หลายตัว — กันงานวิดีโอกับกล้องสดชนกัน
        log.info("engine ready in %.1fs (device=%s, plate_model=%s)", time.time() - t, self.cfg.device,
                 self.plates.available)

    # ------------------------------------------------------------------ public
    def process(
        self,
        video_path: str | Path,
        out_dir: str | Path,
        on_event: Callable[[VehicleEvent], None] | None = None,
        on_progress: Callable[[Progress], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        typhoon: bool | None = None,
        on_event_update: Callable[[VehicleEvent], None] | None = None,
    ) -> dict:
        cfg = self.cfg
        use_typhoon = cfg.typhoon if typhoon is None else typhoon
        if use_typhoon and not self.typhoon_available():
            log.warning("ขอใช้ Typhoon แต่ยังไม่ได้ติดตั้ง/ดาวน์โหลด (make typhoon) — ข้ามขั้นตอนนี้")
            use_typhoon = False
        w_analyze = 0.75 if use_typhoon else 0.9   # สัดส่วนของแถบความคืบหน้า
        out_dir = Path(out_dir)
        (out_dir / "events").mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"เปิดวิดีโอไม่ได้: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not (1 <= fps <= 240):
            fps = 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        stride = cfg.frame_stride or max(1, round(fps / cfg.target_fps))
        # ByteTrack จำรถที่หายไปได้ 30 เฟรมที่ประมวลผล — ต้องรอนานกว่านั้นก่อนสรุปผล
        lost_frames = max(int(cfg.lost_seconds * fps), stride * 32)
        log.info("video %s: %dx%d @ %.2ffps, %d frames, stride=%d", video_path, W, H, fps, total, stride)

        self.tracker.reset()
        tracks: dict[int, _Track] = {}
        generation: Counter = Counter()
        frame_items: dict[int, list[tuple[str, str, tuple, tuple | None]]] = {}
        labels: dict[str, str] = {}
        recent_plates: dict[str, float] = {}   # เลขทะเบียน → เวลาที่เจอล่าสุด (กันบันทึกซ้ำ)
        dup_labels: dict[str, str] = {}        # track key ที่ซ้ำกับคันก่อน → เลขทะเบียน
        events: list[VehicleEvent] = []

        def finalize(tr: _Track) -> None:
            ev = self._finalize(tr, fps, out_dir, recent_plates, dup_labels)
            cls = tr.cls_votes.most_common(1)[0][0] if tr.cls_votes else "car"
            if tr.hits >= cfg.min_track_hits:
                labels[tr.key] = f"{TYPE_TH.get(cls, cls)}"
            if ev is not None:
                labels[tr.key] = f"{ev.plate_text}" if ev.plate_text else labels.get(tr.key, "")
                events.append(ev)
                if on_event:
                    on_event(ev)
            elif tr.key in dup_labels:  # ซ้ำกับคันก่อนหน้า
                labels[tr.key] = dup_labels[tr.key]

        t0 = time.time()
        last_report = 0.0
        idx = -1
        processed = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            if idx % stride:
                continue
            if should_stop and should_stop():
                raise Cancelled()

            vehicles = self.tracker.track(frame)
            plates = self.plates.detect(frame) if self.plates.available else []
            items = []
            for v in assign_plates(vehicles, plates):
                tr = tracks.get(v.track_id)
                if tr is None:
                    generation[v.track_id] += 1
                    tr = _Track(key=f"{v.track_id}-{generation[v.track_id]}", track_id=v.track_id,
                                first_frame=idx, last_frame=idx)
                    tracks[v.track_id] = tr
                tr.last_frame = idx
                tr.hits += 1
                tr.max_conf = max(tr.max_conf, v.box.conf)
                tr.max_width = max(tr.max_width, (v.box.x2 - v.box.x1) / W)
                tr.cls_votes[v.cls] += v.box.conf
                self._consider(tr, v, frame, idx, W, H)
                items.append((tr.key, v.cls, v.box.as_int(), v.plate.as_int() if v.plate else None))
            frame_items[idx] = items

            for tid in [t for t, tr in tracks.items() if idx - tr.last_frame > lost_frames]:
                finalize(tracks.pop(tid))

            processed += 1
            now = time.time()
            if on_progress and now - last_report > 0.5:
                last_report = now
                speed = idx / max(now - t0, 1e-6)
                frac = idx / total if total else 0.0
                eta = (total - idx) / speed * 1.1 if total and speed > 0 else None
                on_progress(Progress(w_analyze * frac, "analyzing", idx, total, round(speed, 1),
                                     round(eta, 1) if eta else None, len(events)))
        cap.release()
        total = idx + 1
        for tr in list(tracks.values()):
            finalize(tr)
        analyze_sec = time.time() - t0

        refined = 0
        if use_typhoon:
            refined = self._refine_pass(events, out_dir, labels, on_progress, on_event_update, should_stop, w_analyze)

        # -------- วาดกรอบ: วาดกรอบลงวิดีโอผลลัพธ์
        out_video = out_dir / "annotated.mp4"
        self._render(video_path, out_video, fps, total, stride, frame_items, labels, on_progress, should_stop,
                     len(events))
        summary = {
            "fps": fps, "width": W, "height": H, "total_frames": total, "duration_sec": total / fps,
            "stride": stride, "events": len(events), "analyze_sec": round(analyze_sec, 1),
            "elapsed_sec": round(time.time() - t0, 1), "output_video": out_video.name,
            "plate_model": self.plates.available, "plate_ocr_model": self.reader.char is not None,
            "typhoon": use_typhoon, "typhoon_refined": refined,
            "device": cfg.device,
        }
        if on_progress:
            on_progress(Progress(1.0, "done", total, total, 0, 0, len(events)))
        return summary

    # ----------------------------------------------------------------- typhoon
    @staticmethod
    def typhoon_available() -> bool:
        from .typhoon import is_available

        return is_available()

    def typhoon_model(self):
        # เรียกภายใต้ _typhoon_lock เท่านั้น
        if self._typhoon is None:
            from .typhoon import TyphoonOCR

            t = time.time()
            self._typhoon = TyphoonOCR(self.cfg.device)
            log.info("โหลด Typhoon OCR 3B %.0fs", time.time() - t)
        return self._typhoon

    def release_typhoon(self) -> None:
        """คืนหน่วยความจำ ~7.5 GB หลังใช้."""
        with self._typhoon_lock:
            if self._typhoon is None:
                return
            self._typhoon = None
            gc.collect()
            try:
                import torch

                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass

    def refine_with_typhoon(self, reading, plate_img: np.ndarray):
        """อ่านซ้ำด้วย Typhoon แล้วรวมผล (ใช้ใน refine pass และ benchmark)."""
        from .typhoon import merge

        if plate_img is None or plate_img.size == 0:
            return reading
        with self._typhoon_lock, locks.guard():
            ty = self.typhoon_model().read(plate_img)
        return merge(reading, ty)

    def _refine_pass(self, events, out_dir: Path, labels, on_progress, on_event_update, should_stop,
                     start: float) -> int:
        from .postprocess import PlateReading

        todo = [e for e in events if e.plate_img]
        if not todo:
            return 0
        if on_progress:
            on_progress(Progress(start, "refining", 0, len(todo), 0, None, len(events)))
        changed = 0
        t0 = time.time()
        try:
            for i, ev in enumerate(todo, 1):
                if should_stop and should_stop():
                    raise Cancelled()
                img = cv2.imread(str(out_dir / ev.plate_img))
                base = PlateReading(text=ev.plate_text, province=ev.plate_province, conf=ev.plate_conf,
                                    valid=ev.plate_valid, raw=ev.ocr_raw)
                before = (ev.plate_text, ev.plate_province)
                try:
                    r = self.refine_with_typhoon(base, img)
                except Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001 — Typhoon พลาด 1 คัน ไม่ควรทำให้ทั้งงานล้ม
                    log.warning("Typhoon อ่าน %s ไม่ได้: %s", ev.plate_img, e)
                    continue
                ev.ocr_raw = r.raw
                if (r.text, r.province) != before:
                    if r.extras.get("source") == "typhoon":
                        ev.ocr_engine = "typhoon"
                    ev.plate_text, ev.plate_province, ev.plate_valid = r.text, r.province, r.valid
                    ev.plate_conf = round(r.conf, 4)
                    if ev.plate_text:
                        labels[ev.key] = ev.plate_text
                    changed += 1
                    if on_event_update:
                        on_event_update(ev)
                if on_progress:
                    speed = i / max(time.time() - t0, 1e-6)
                    on_progress(Progress(start + (0.9 - start) * i / len(todo), "refining", i, len(todo),
                                         round(speed, 2), round((len(todo) - i) / speed, 1), len(events)))
        finally:
            if not self.cfg.keep_typhoon_loaded:
                self.release_typhoon()
        return changed

    # ----------------------------------------------------------------- helpers
    def _consider(self, tr: _Track, v, frame: np.ndarray, idx: int, W: int, H: int) -> None:
        """ให้คะแนนเฟรมนี้ของรถคันนี้ แล้วเก็บไว้ถ้าอยู่ใน top-k."""
        b = v.box
        edge = b.x1 < 4 or b.y1 < 4 or b.x2 > W - 4 or b.y2 > H - 4
        edge_pen = 0.5 if edge else 1.0
        if v.plate is not None:
            px1, py1, px2, py2 = _clip(v.plate, W, H)
            pcrop = frame[py1:py2, px1:px2]
            if pcrop.size == 0:
                return
            score = 1000 + v.plate.conf * math.sqrt(v.plate.area) * min(sharpness(pcrop) / 50, 4) * edge_pen
        else:
            x1, y1, x2, y2 = _clip(b, W, H)
            car = frame[y1:y2, x1:x2]
            if car.size == 0:
                return
            small = cv2.resize(car, (160, max(1, int(160 * car.shape[0] / max(car.shape[1], 1)))))
            score = math.sqrt(b.area) * min(sharpness(small) / 100, 3) * edge_pen * b.conf

        k = self.cfg.top_k
        if len(tr.candidates) >= k and score <= tr.candidates[-1].score:
            return
        cx1, cy1, cx2, cy2 = _clip(b, W, H, pad=0.04)
        car = frame[cy1:cy2, cx1:cx2].copy()
        plate_crop, plate_box = None, None
        if v.plate is not None:
            px1, py1, px2, py2 = _clip(v.plate, W, H, pad=0.08)
            plate_crop = frame[py1:py2, px1:px2].copy()
            plate_box = (px1 - cx1, py1 - cy1, px2 - cx1, py2 - cy1)
        tr.candidates.append(_Candidate(score, idx, car, plate_crop, plate_box))
        tr.candidates.sort(key=lambda c: -c.score)
        del tr.candidates[k:]

    def _finalize(self, tr: _Track, fps: float, out_dir: Path, recent: dict, dups: dict) -> VehicleEvent | None:
        with self.finalize_lock:
            return self._finalize_locked(tr, fps, out_dir, recent, dups)

    def _finalize_locked(self, tr: _Track, fps: float, out_dir: Path, recent: dict, dups: dict) -> VehicleEvent | None:
        if tr.hits < self.cfg.min_track_hits or not tr.candidates or tr.max_width < self.cfg.min_vehicle_frac:
            return None
        readings, boxes = [], []
        for c in tr.candidates:
            if c.plate is not None:
                r, pbox = self.reader.read_plate(c.plate), c.plate_box
            else:
                r, pbox = self.reader.find_and_read(c.car)
            readings.append(r)
            boxes.append(pbox)
        result = vote(readings)

        # เลือกเฟรมตัวแทน: เฟรมที่อ่านได้ตรงกับผล vote และคะแนนดีที่สุด
        best_i = next((i for i, r in enumerate(readings) if result.text and r.text == result.text), 0)
        best = tr.candidates[best_i]
        offset = best.frame_idx / fps

        plate_img = best.plate
        if plate_img is None and boxes[best_i] is not None:
            x1, y1, x2, y2 = boxes[best_i]
            plate_img = best.car[y1:y2, x1:x2]
        if result.text:
            prev = recent.get(result.text)
            if prev is not None and abs(offset - prev) < self.cfg.dedup_seconds:
                dups[tr.key] = result.text
                return None
            recent[result.text] = offset

        car_rel = f"events/{tr.key}_car.jpg"
        cv2.imwrite(str(out_dir / car_rel), best.car, [cv2.IMWRITE_JPEG_QUALITY, 90])
        plate_rel = None
        if plate_img is not None and plate_img.size:
            if plate_img.shape[0] < 96:
                s = 96 / plate_img.shape[0]
                plate_img = cv2.resize(plate_img, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            plate_rel = f"events/{tr.key}_plate.jpg"
            cv2.imwrite(str(out_dir / plate_rel), plate_img, [cv2.IMWRITE_JPEG_QUALITY, 92])

        cls = tr.cls_votes.most_common(1)[0][0]
        return VehicleEvent(
            track_id=tr.track_id, vehicle_type=cls, vehicle_conf=round(tr.max_conf, 3),
            video_offset_sec=round(offset, 2), first_seen_sec=round(tr.first_frame / fps, 2),
            last_seen_sec=round(tr.last_frame / fps, 2), plate_text=result.text, plate_province=result.province,
            plate_conf=result.conf, plate_valid=result.valid, car_img=car_rel, plate_img=plate_rel,
            ocr_raw=result.raw, votes=int(result.extras.get("votes", 0)),
            ocr_engine=(readings[best_i].extras.get("source", "char-ocr") if result.text else ""), key=tr.key,
        )

    def _render(self, src, dst: Path, fps, total, stride, frame_items, labels, on_progress, should_stop,
                n_events) -> None:
        import imageio_ffmpeg

        cap = cv2.VideoCapture(str(src))
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        scale = min(1.0, self.cfg.max_output_width / max(W, 1))
        ow, oh = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
        writer = imageio_ffmpeg.write_frames(
            str(dst), (ow, oh), fps=fps, codec="libx264", pix_fmt_in="bgr24", pix_fmt_out="yuv420p",
            quality=None, macro_block_size=2, ffmpeg_log_level="error",
            output_params=["-preset", "veryfast", "-crf", "26", "-movflags", "+faststart"],
        )
        writer.send(None)
        t0 = time.time()
        last = 0.0
        idx = -1
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                idx += 1
                if should_stop and should_stop() and idx % 50 == 0:
                    raise Cancelled()
                items = frame_items.get(idx - idx % stride, [])
                draw = [{"box": box, "plate": plate, "cls": cls, "label": labels[key]}
                        for key, cls, box, plate in items if labels.get(key)]
                frame = draw_frame(frame, draw, self.cfg.font_path)
                if scale != 1.0 or (ow, oh) != (W, H):
                    frame = cv2.resize(frame, (ow, oh), interpolation=cv2.INTER_AREA)
                writer.send(np.ascontiguousarray(frame))
                now = time.time()
                if on_progress and now - last > 0.5:
                    last = now
                    speed = idx / max(now - t0, 1e-6)
                    on_progress(Progress(0.9 + 0.1 * idx / max(total, 1), "rendering", idx, total,
                                         round(speed, 1), round((total - idx) / max(speed, 1e-6), 1), n_events))
        finally:
            cap.release()
            writer.close()
