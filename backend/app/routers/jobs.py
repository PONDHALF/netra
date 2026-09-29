from __future__ import annotations

import asyncio
import io
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import ALLOWED_EXT, DATA_DIR, OUTPUT_DIR, UPLOAD_DIR
from ..db import SessionLocal, get_db
from ..models import Event, Job, Source
from ..schemas import JobOut, JobStats
from ..worker import hub, runner

router = APIRouter()


def job_stats(db: Session, job_id: int) -> JobStats:
    rows = db.query(Event.vehicle_type, func.count()).filter(Event.job_id == job_id).group_by(Event.vehicle_type).all()
    by_type = {t: n for t, n in rows}
    read = db.query(func.count()).filter(Event.job_id == job_id, Event.plate_text.isnot(None)).scalar() or 0
    corrected = db.query(func.count()).filter(Event.job_id == job_id, Event.is_corrected.is_(True)).scalar() or 0
    return JobStats(total=sum(by_type.values()), by_type=by_type, plates_read=read, corrected=corrected)


def job_out(db: Session, job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.stats = job_stats(db, job.id)
    return out


@router.post("/api/videos", response_model=JobOut, status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    source_name: str = Form(""),
    location: str = Form(""),
    video_start: datetime | None = Form(None),
    use_typhoon: bool = Form(False),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"ไม่รองรับไฟล์ {ext or '(ไม่มีนามสกุล)'} — รองรับ {', '.join(sorted(ALLOWED_EXT))}")
    safe = re.sub(r"[^\w.\-]+", "_", Path(file.filename).stem)[:60]
    dest = UPLOAD_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}-{safe}{ext}"
    with dest.open("wb") as f:
        while chunk := await file.read(8 * 1024 * 1024):
            f.write(chunk)

    name = source_name.strip() or Path(file.filename).stem
    source = db.query(Source).filter(Source.name == name, Source.type == "video").first()
    if source is None:
        source = Source(name=name, type="video", location=location.strip() or None)
        db.add(source)
    elif location.strip():
        source.location = location.strip()
    job = Job(source=source, file_path=dest.relative_to(DATA_DIR).as_posix(), original_name=file.filename,
              video_start=video_start.replace(tzinfo=None) if video_start else None, use_typhoon=use_typhoon)
    db.add(job)
    db.commit()
    runner.submit(job.id)
    return job_out(db, job)


@router.get("/api/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db)):
    return [job_out(db, j) for j in db.query(Job).order_by(Job.id.desc()).limit(200).all()]


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "ไม่พบงาน")
    return job_out(db, job)


@router.post("/api/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "ไม่พบงาน")
    if job.status in ("queued", "processing"):
        runner.cancel(job_id)
        if job.status == "queued":
            job.status = "cancelled"
            db.commit()
    return job_out(db, job)


@router.post("/api/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "ไม่พบงาน")
    if job.status in ("queued", "processing"):
        raise HTTPException(409, "งานนี้กำลังทำงานอยู่")
    db.query(Event).filter(Event.job_id == job_id).delete()
    shutil.rmtree(OUTPUT_DIR / str(job_id), ignore_errors=True)
    job.status, job.progress, job.error, job.output_path, job.summary = "queued", 0.0, None, None, None
    db.commit()
    runner.submit(job_id)
    return job_out(db, job)


@router.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "ไม่พบงาน")
    if job.status == "processing":
        raise HTTPException(409, "กรุณายกเลิกงานก่อนลบ")
    runner.cancel(job_id)
    video = DATA_DIR / job.file_path
    db.delete(job)
    db.commit()
    video.unlink(missing_ok=True)
    shutil.rmtree(OUTPUT_DIR / str(job_id), ignore_errors=True)


@router.get("/api/jobs/{job_id}/images.zip")
def download_images(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "ไม่พบงาน")
    events = db.query(Event).filter(Event.job_id == job_id).order_by(Event.video_offset_sec).all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # jpg บีบอัดแล้ว
        for e in events:
            label = re.sub(r"\s+", "", e.plate_text or "ไม่ทราบป้าย")
            t = f"{int((e.video_offset_sec or 0) // 60):02d}m{int((e.video_offset_sec or 0) % 60):02d}s"
            base = f"{e.id:05d}_{t}_{e.vehicle_type}_{label}"
            for kind, rel in (("car", e.car_img), ("plate", e.plate_img)):
                if rel and (DATA_DIR / rel).exists():
                    z.write(DATA_DIR / rel, f"{kind}/{base}.jpg")
    buf.seek(0)
    name = f"netra-job{job_id}-images.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.websocket("/ws/jobs/{job_id}")
async def job_ws(ws: WebSocket, job_id: int):
    await ws.accept()
    q = hub.subscribe(job_id)
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                await ws.send_json({"type": "error", "message": "ไม่พบงาน"})
                return
            await ws.send_json({"type": "status", "status": job.status, "progress": job.progress,
                                "stage": job.stage, "error": job.error})
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(job_id, q)
