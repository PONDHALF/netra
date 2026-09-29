"""ประมวลผลวิดีโอเบื้องหลัง (ทีละงาน เพราะใช้ GPU ร่วมกัน) และกระจายความคืบหน้าผ่าน WebSocket."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from .config import DATA_DIR, OUTPUT_DIR, PRELOAD_ENGINE
from .db import SessionLocal
from .models import Event, Job
from .schemas import EventOut

log = logging.getLogger("netra.worker")


class Hub:
    """ส่งข้อความจาก worker thread ไปยัง WebSocket ของแต่ละ job."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subs: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, job_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subs[job_id].add(q)
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue) -> None:
        self.subs[job_id].discard(q)
        if not self.subs[job_id]:
            self.subs.pop(job_id, None)

    def publish(self, job_id: int, msg: dict) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._fanout, job_id, msg)

    def _fanout(self, job_id: int, msg: dict) -> None:
        for q in list(self.subs.get(job_id, ())):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


class JobRunner:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="netra-job")
        self._engine = None
        self._engine_lock = threading.Lock()
        self._cancel: set[int] = set()
        self.current: int | None = None

    @property
    def engine(self):
        with self._engine_lock:
            if self._engine is None:
                from engine import Engine

                self._engine = Engine()
            return self._engine

    def start(self) -> None:
        with SessionLocal() as db:
            # งานที่ค้างจากการปิดเซิร์ฟเวอร์ครั้งก่อน → เริ่มใหม่
            pending = db.query(Job).filter(Job.status.in_(["queued", "processing"])).order_by(Job.id).all()
            for job in pending:
                db.query(Event).filter(Event.job_id == job.id).delete()
                job.status, job.progress = "queued", 0.0
            db.commit()
            ids = [j.id for j in pending]
        if PRELOAD_ENGINE:
            self.pool.submit(self._warmup)
        for jid in ids:
            self.submit(jid)

    def _warmup(self) -> None:
        try:
            _ = self.engine
        except Exception:
            log.exception("โหลด engine ไม่สำเร็จ")

    def submit(self, job_id: int) -> None:
        self.pool.submit(self._run, job_id)

    def cancel(self, job_id: int) -> None:
        self._cancel.add(job_id)

    def shutdown(self) -> None:
        if self.current is not None:
            self._cancel.add(self.current)
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    def _run(self, job_id: int) -> None:
        from engine import Cancelled, Progress, VehicleEvent

        if job_id in self._cancel:
            return
        db = SessionLocal()
        job = db.get(Job, job_id)
        if job is None:
            return
        self.current = job_id
        out_dir = OUTPUT_DIR / str(job_id)
        out_rel = out_dir.relative_to(DATA_DIR).as_posix()
        video = DATA_DIR / job.file_path
        start = job.video_start or job.created_at
        try:
            job.status, job.started_at, job.stage, job.progress = "processing", datetime.now(), "loading", 0.0
            job.thumb_path = self._thumbnail(video, out_dir, out_rel)
            db.commit()
            self._publish_job(job)
            engine = self.engine
            rows_by_key: dict[str, int] = {}

            def publish_event(row: Event, kind: str) -> None:
                out = EventOut.model_validate(row)
                out.source_name = job.source.name
                self.hub.publish(job.id, {"type": kind, "event": out.model_dump(mode="json")})

            def on_event(ev: VehicleEvent) -> None:
                row = Event(
                    source_id=job.source_id, job_id=job.id, track_id=ev.track_id,
                    ts=start + timedelta(seconds=ev.video_offset_sec), video_offset_sec=ev.video_offset_sec,
                    first_seen_sec=ev.first_seen_sec, last_seen_sec=ev.last_seen_sec,
                    vehicle_type=ev.vehicle_type, vehicle_conf=ev.vehicle_conf, plate_text=ev.plate_text,
                    plate_province=ev.plate_province, plate_conf=ev.plate_conf, plate_valid=ev.plate_valid,
                    car_img=f"{out_rel}/{ev.car_img}", plate_img=f"{out_rel}/{ev.plate_img}" if ev.plate_img else None,
                    ocr_raw=ev.ocr_raw, ocr_engine=ev.ocr_engine or None,
                )
                db.add(row)
                db.commit()
                rows_by_key[ev.key] = row.id
                publish_event(row, "event")

            def on_event_update(ev: VehicleEvent) -> None:
                row = db.get(Event, rows_by_key.get(ev.key, -1))
                if row is None or row.is_corrected:  # ไม่ทับค่าที่ผู้ใช้แก้เองแล้ว
                    return
                row.plate_text, row.plate_province = ev.plate_text, ev.plate_province
                row.plate_conf, row.plate_valid = ev.plate_conf, ev.plate_valid
                row.ocr_raw, row.ocr_engine = ev.ocr_raw, ev.ocr_engine or row.ocr_engine
                db.commit()
                publish_event(row, "event_update")

            def on_progress(p: Progress) -> None:
                job.progress, job.stage, job.eta_sec = round(p.progress, 4), p.stage, p.eta_sec
                db.commit()
                self.hub.publish(job.id, {"type": "progress", "progress": p.progress, "stage": p.stage,
                                          "eta_sec": p.eta_sec, "fps": p.fps, "frame": p.frame,
                                          "total_frames": p.total_frames, "events": p.events})

            summary = engine.process(video, out_dir, on_event=on_event, on_progress=on_progress,
                                     should_stop=lambda: job_id in self._cancel, typhoon=job.use_typhoon,
                                     on_event_update=on_event_update)
            job.status, job.progress, job.stage, job.eta_sec = "done", 1.0, "done", 0
            job.summary = summary
            job.duration_sec = summary["duration_sec"]
            job.output_path = f"{out_rel}/{summary['output_video']}"
            job.finished_at = datetime.now()
            db.commit()
        except Cancelled:
            db.rollback()
            job.status, job.finished_at = "cancelled", datetime.now()
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            db.rollback()
            job.status, job.error, job.finished_at = "failed", f"{type(e).__name__}: {e}", datetime.now()
            db.commit()
        finally:
            self._publish_job(job)
            self._cancel.discard(job_id)
            self.current = None
            db.close()

    def _publish_job(self, job: Job) -> None:
        self.hub.publish(job.id, {"type": "status", "status": job.status, "progress": job.progress,
                                  "stage": job.stage, "error": job.error})

    @staticmethod
    def _thumbnail(video: Path, out_dir: Path, out_rel: str) -> str | None:
        out_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(video))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if n > 10:
            cap.set(cv2.CAP_PROP_POS_FRAMES, n // 10)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return None
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (480, int(480 * h / w)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out_dir / "thumb.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return f"{out_rel}/thumb.jpg"


hub = Hub()
runner = JobRunner(hub)
