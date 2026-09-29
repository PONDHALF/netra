"""กล้องสด: รับภาพต่อเนื่อง (RTSP / HTTP / webcam / ไฟล์วิดีโอเล่นวน) → ประมวลผล real-time → ภาพสด + event

1 กล้อง = 1 CameraRunner (thread) ที่มี
  - reader thread อ่านเฟรมตลอดเวลา เก็บไว้แค่เฟรมล่าสุด (ทิ้งเฟรมเก่า → ดีเลย์ต่ำแม้ประมวลผลช้ากว่ากล้อง)
  - ลูปประมวลผลที่ ~target_fps: StreamSession → ภาพวาดกรอบ (JPEG สำหรับ MJPEG) + event เมื่อรถออกจากภาพ
  - ต่อใหม่อัตโนมัติเมื่อกล้องหลุด (backoff 2 → 30 วินาที)
"""
from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

from .config import DATA_DIR, ROOT
from .db import SessionLocal
from .models import Event, Source
from .schemas import EventOut

log = logging.getLogger("netra.cameras")

LIVE_CHANNEL = 0  # ช่อง WebSocket ของหน้า Live (job id เริ่มที่ 1)
CAMERAS_DIR = DATA_DIR / "cameras"
JPEG_MAX_WIDTH = 1280

# RTSP ผ่าน TCP เสถียรกว่า UDP บนเครือข่ายทั่วไป, timeout 5 วินาทีเพื่อให้ต่อใหม่ได้เร็ว
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000|timeout;5000000")


def mask_url(url: str) -> str:
    """ซ่อนรหัสผ่านใน URL กล้อง (rtsp://user:pass@host → rtsp://user:***@host)."""
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", url or "")


def resolve_source(url: str) -> tuple[int | str, bool]:
    """คืน (แหล่งภาพสำหรับ OpenCV, เป็นไฟล์ที่ต้องเล่นวนหรือไม่)."""
    u = url.strip()
    if u.isdigit():
        return int(u), False  # webcam index
    if "://" in u:
        return u, False
    for base in (Path(u), ROOT / u, DATA_DIR / u):
        if base.is_file():
            return str(base), True
    return u, False


class CameraRunner:
    def __init__(self, manager: CameraManager, cam_id: int, name: str, url: str):
        self.manager, self.cam_id, self.name, self.url = manager, cam_id, name, url
        self._stop = threading.Event()
        self._frame_cond = threading.Condition()
        self._latest = None
        self._latest_no = 0
        self.jpeg: bytes | None = None
        self.jpeg_no = 0
        self.status = {"state": "starting", "fps": 0.0, "error": None, "width": None, "height": None,
                       "events": 0, "started_at": time.time()}
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"netra-cam-{cam_id}")

    # ------------------------------------------------------------ control
    def start(self) -> None:
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        with self._frame_cond:
            self._frame_cond.notify_all()
        if wait:
            self._thread.join(timeout=15)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    # ------------------------------------------------------------ threads
    def _reader(self, cap, is_file: bool, src_fps: float, done: threading.Event) -> None:
        interval = 1.0 / src_fps if is_file else 0.0
        next_t = time.time()
        while not self._stop.is_set() and not done.is_set():
            ok, frame = cap.read()
            if not ok:
                if is_file:  # วิดีโอจบ → เล่นวนใหม่
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                if not ok:
                    done.set()
                    break
            with self._frame_cond:
                self._latest = frame
                self._latest_no += 1
                self._frame_cond.notify_all()
            if interval:  # ไฟล์: จำลองความเร็วเท่ากล้องจริง
                next_t += interval
                delay = next_t - time.time()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.time()
        with self._frame_cond:
            self._frame_cond.notify_all()

    def _run(self) -> None:
        from engine.stream import StreamSession

        backoff = 2.0
        try:
            engine = self.manager.engine()
        except Exception as e:  # noqa: BLE001
            self._set(state="error", error=f"โหลด AI ไม่สำเร็จ: {e}")
            return
        target_fps = engine.cfg.target_fps
        while not self._stop.is_set():
            src, is_file = resolve_source(self.url)
            self._set(state="connecting", error=None)
            cap = cv2.VideoCapture(src) if isinstance(src, int) else cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap.release()
                self._set(state="reconnecting", error=f"เชื่อมต่อกล้องไม่ได้: {mask_url(self.url)}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 2.0
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:  # noqa: BLE001
                pass
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            if not 1 <= src_fps <= 120:
                src_fps = 25.0
            reader_done = threading.Event()
            reader = threading.Thread(target=self._reader, args=(cap, is_file, src_fps, reader_done), daemon=True,
                                      name=f"netra-cam-{self.cam_id}-reader")
            reader.start()

            tag = datetime.now().strftime("%Y%m%d-%H%M%S")
            out_dir = CAMERAS_DIR / str(self.cam_id) / tag
            session = StreamSession(engine, out_dir, fps=target_fps, tag=tag,
                                    on_event=lambda ev, ts, d=out_dir: self._on_event(ev, ts, d))
            self._set(state="online", error=None)
            last_no, interval, ema, last_t = 0, 1.0 / target_fps, 0.0, time.time()
            try:
                while not self._stop.is_set():
                    with self._frame_cond:
                        self._frame_cond.wait_for(lambda: self._latest_no != last_no or self._stop.is_set()
                                                  or reader_done.is_set(), timeout=10)
                        if self._latest_no == last_no:
                            if reader_done.is_set() or not self._stop.is_set():
                                raise ConnectionError("กล้องไม่ส่งภาพมาเกิน 10 วินาที")
                            break
                        frame, last_no = self._latest, self._latest_no
                    t = time.time()
                    annotated = session.process(frame)
                    self._publish_frame(annotated)
                    now = time.time()
                    ema = 0.9 * ema + 0.1 * (1.0 / max(now - last_t, 1e-6)) if ema else 1.0 / max(now - last_t, 1e-6)
                    last_t = now
                    self._set(fps=round(ema, 1), width=frame.shape[1], height=frame.shape[0])
                    spare = interval - (time.time() - t)  # ไม่ประมวลผลเร็วเกิน target_fps (ประหยัด GPU)
                    if spare > 0:
                        self._stop.wait(spare)
            except Exception as e:  # noqa: BLE001
                log.warning("กล้อง %s: %s", self.name, e)
                self._set(state="reconnecting", error=str(e))
            finally:
                reader_done.set()
                reader.join(timeout=5)
                cap.release()
                session.close()
            if not self._stop.is_set():
                self._stop.wait(backoff)
        self._set(state="stopped", fps=0.0)

    # ------------------------------------------------------------ helpers
    def _set(self, **kw) -> None:
        self.status.update(kw)

    def _publish_frame(self, frame) -> None:
        h, w = frame.shape[:2]
        if w > JPEG_MAX_WIDTH:
            frame = cv2.resize(frame, (JPEG_MAX_WIDTH, int(h * JPEG_MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            self.jpeg = buf.tobytes()
            self.jpeg_no += 1

    def _on_event(self, ev, ts: float, out_dir: Path) -> None:
        rel = out_dir.relative_to(DATA_DIR).as_posix()
        with SessionLocal() as db:
            row = Event(
                source_id=self.cam_id, job_id=None, track_id=ev.track_id, ts=datetime.fromtimestamp(ts),
                vehicle_type=ev.vehicle_type, vehicle_conf=ev.vehicle_conf, plate_text=ev.plate_text,
                plate_province=ev.plate_province, plate_conf=ev.plate_conf, plate_valid=ev.plate_valid,
                car_img=f"{rel}/{ev.car_img}", plate_img=f"{rel}/{ev.plate_img}" if ev.plate_img else None,
                ocr_raw=ev.ocr_raw, ocr_engine=ev.ocr_engine or None,
            )
            db.add(row)
            db.commit()
            out = EventOut.model_validate(row)
            out.source_name = self.name
        self.status["events"] += 1
        self.manager.publish({"type": "event", "camera_id": self.cam_id, "event": out.model_dump(mode="json")})
        self.manager.maybe_refine(row.id, ev)


class CameraManager:
    def __init__(self, hub, job_runner):
        self.hub, self.job_runner = hub, job_runner
        self.runners: dict[int, CameraRunner] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._refine_q: queue.Queue = queue.Queue(maxsize=500)
        self._typhoon: bool | None = None

    def engine(self):
        return self.job_runner.engine  # ใช้ Engine ตัวเดียวกับงานวิดีโอ (โมเดลโหลดครั้งเดียว)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        demo = os.getenv("NETRA_DEMO_CAMERA", "").strip()
        with SessionLocal() as db:
            if demo and not db.query(Source).filter(Source.type == "camera").first():
                db.add(Source(name="กล้องจำลอง (วิดีโอเล่นวน)", type="camera", url=demo, enabled=True,
                              location="สำหรับทดสอบ — เปลี่ยน URL เป็นกล้องจริงได้"))
                db.commit()
            cams = db.query(Source).filter(Source.type == "camera", Source.enabled.is_(True)).all()
            todo = [(c.id, c.name, c.url) for c in cams if c.url]
        for cid, name, url in todo:
            self.start_camera(cid, name, url)
        threading.Thread(target=self._status_loop, daemon=True, name="netra-cam-status").start()
        threading.Thread(target=self._refine_loop, daemon=True, name="netra-cam-typhoon").start()

    def shutdown(self) -> None:
        self._stop.set()
        for r in list(self.runners.values()):
            r.stop(wait=False)

    def start_camera(self, cam_id: int, name: str, url: str) -> None:
        with self._lock:
            old = self.runners.pop(cam_id, None)
        if old:
            old.stop()
        r = CameraRunner(self, cam_id, name, url)
        with self._lock:
            self.runners[cam_id] = r
        r.start()
        log.info("เริ่มกล้อง %s (%s)", name, mask_url(url))

    def stop_camera(self, cam_id: int) -> None:
        with self._lock:
            r = self.runners.pop(cam_id, None)
        if r:
            r.stop()

    def status(self, cam_id: int) -> dict:
        r = self.runners.get(cam_id)
        if r is None:
            return {"state": "stopped", "fps": 0.0, "error": None, "width": None, "height": None, "events": 0}
        return dict(r.status)

    def publish(self, msg: dict) -> None:
        self.hub.publish(LIVE_CHANNEL, msg)

    def _status_loop(self) -> None:
        while not self._stop.wait(2.0):
            if self.hub.subs.get(LIVE_CHANNEL):
                self.publish({"type": "cameras", "cameras": {str(k): self.status(k) for k in list(self.runners)}})

    # ------------------------------------------------------------ Typhoon (เบื้องหลัง)
    def _typhoon_on(self) -> bool:
        if self._typhoon is None:
            from engine.typhoon import is_available

            eng = self.engine()
            self._typhoon = bool(eng.cfg.typhoon and is_available())
        return self._typhoon

    def maybe_refine(self, event_id: int, ev) -> None:
        """ส่งป้ายที่อ่านไม่ครบ/ไม่มั่นใจให้ Typhoon อ่านซ้ำเบื้องหลัง — รายการในหน้า Live จะอัปเดตเอง."""
        if not ev.plate_img or (ev.plate_valid and ev.plate_conf >= 0.5 and ev.plate_province):
            return
        if not self._typhoon_on():
            return
        try:
            self._refine_q.put_nowait(event_id)
        except queue.Full:
            pass

    def _refine_loop(self) -> None:
        from engine.postprocess import PlateReading

        while not self._stop.is_set():
            try:
                event_id = self._refine_q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                with SessionLocal() as db:
                    row = db.get(Event, event_id)
                    if row is None or row.is_corrected or not row.plate_img:
                        continue
                    img = cv2.imread(str(DATA_DIR / row.plate_img))
                    base = PlateReading(text=row.plate_text, province=row.plate_province, conf=row.plate_conf,
                                        valid=row.plate_valid, raw=row.ocr_raw or "")
                    before = (row.plate_text, row.plate_province)
                    r = self.engine().refine_with_typhoon(base, img)
                    if (r.text, r.province) == before:
                        continue
                    row.plate_text, row.plate_province, row.plate_valid = r.text, r.province, r.valid
                    row.plate_conf, row.ocr_raw = round(r.conf, 4), r.raw
                    if r.extras.get("source") == "typhoon":
                        row.ocr_engine = "typhoon"
                    db.commit()
                    out = EventOut.model_validate(row)
                    out.source_name = row.source.name if row.source else None
                self.publish({"type": "event_update", "camera_id": row.source_id, "event": out.model_dump(mode="json")})
            except Exception:  # noqa: BLE001
                log.exception("Typhoon อ่านซ้ำ event %s ไม่สำเร็จ", event_id)
