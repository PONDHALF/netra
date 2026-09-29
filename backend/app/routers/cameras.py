"""กล้องสด: จัดการกล้อง, ภาพสด (MJPEG), WebSocket หน้า Live"""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..cameras import LIVE_CHANNEL, mask_url
from ..db import get_db
from ..models import Event, Source
from ..worker import hub

router = APIRouter()
manager = None  # ตั้งค่าใน main.py (CameraManager)


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=500)
    location: str | None = None
    enabled: bool = True


class CameraPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=500)
    location: str | None = None
    enabled: bool | None = None


def _out(db: Session, s: Source) -> dict:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    n_today = db.query(func.count()).filter(Event.source_id == s.id, Event.ts >= today).scalar() or 0
    return {"id": s.id, "name": s.name, "location": s.location, "url": mask_url(s.url or ""),
            "enabled": s.enabled, "events_today": n_today, "status": manager.status(s.id)}


def _get(db: Session, cam_id: int) -> Source:
    s = db.get(Source, cam_id)
    if s is None or s.type != "camera":
        raise HTTPException(404, "ไม่พบกล้อง")
    return s


@router.get("/api/cameras")
def list_cameras(db: Session = Depends(get_db)):
    return [_out(db, s) for s in db.query(Source).filter(Source.type == "camera").order_by(Source.id).all()]


@router.post("/api/cameras", status_code=201)
def add_camera(body: CameraIn, db: Session = Depends(get_db)):
    s = Source(name=body.name.strip(), type="camera", url=body.url.strip(), location=body.location, enabled=body.enabled)
    db.add(s)
    db.commit()
    if s.enabled:
        manager.start_camera(s.id, s.name, s.url)
    return _out(db, s)


@router.patch("/api/cameras/{cam_id}")
def update_camera(cam_id: int, body: CameraPatch, db: Session = Depends(get_db)):
    s = _get(db, cam_id)
    url_changed = body.url is not None and body.url.strip() and body.url.strip() != s.url
    if body.name is not None:
        s.name = body.name.strip()
    if url_changed:
        s.url = body.url.strip()
    if body.location is not None:
        s.location = body.location
    if body.enabled is not None:
        s.enabled = body.enabled
    db.commit()
    if not s.enabled:
        manager.stop_camera(s.id)
    elif url_changed or body.enabled or s.id not in manager.runners:
        manager.start_camera(s.id, s.name, s.url)
    return _out(db, s)


@router.post("/api/cameras/{cam_id}/start")
def start_camera(cam_id: int, db: Session = Depends(get_db)):
    return update_camera(cam_id, CameraPatch(enabled=True), db)


@router.post("/api/cameras/{cam_id}/stop")
def stop_camera(cam_id: int, db: Session = Depends(get_db)):
    return update_camera(cam_id, CameraPatch(enabled=False), db)


@router.delete("/api/cameras/{cam_id}", status_code=204)
def delete_camera(cam_id: int, db: Session = Depends(get_db)):
    s = _get(db, cam_id)
    manager.stop_camera(s.id)
    db.delete(s)  # ลบ event ของกล้องนี้ด้วย (cascade)
    db.commit()


@router.get("/api/cameras/{cam_id}/snapshot.jpg")
def snapshot(cam_id: int):
    r = manager.runners.get(cam_id)
    if r is None or r.jpeg is None:
        raise HTTPException(503, "กล้องยังไม่มีภาพ")
    return Response(r.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/api/cameras/{cam_id}/mjpeg")
async def mjpeg(cam_id: int, request: Request):
    """ภาพสดแบบ MJPEG — ใช้ใน <img src> ได้ตรงๆ (ดีเลย์ต่ำ ไม่ต้องมี player)."""
    if cam_id not in manager.runners:
        raise HTTPException(503, "กล้องไม่ได้เปิดอยู่")

    async def frames():
        last = -1
        while not await request.is_disconnected():
            r = manager.runners.get(cam_id)
            if r is None:
                break
            if r.jpeg is not None and r.jpeg_no != last:
                last = r.jpeg_no
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(r.jpeg)).encode()
                       + b"\r\n\r\n" + r.jpeg + b"\r\n")
            await asyncio.sleep(0.03)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@router.websocket("/ws/live")
async def live_ws(ws: WebSocket):
    await ws.accept()
    q = hub.subscribe(LIVE_CHANNEL)
    try:
        await ws.send_json({"type": "cameras", "cameras": {str(k): manager.status(k) for k in list(manager.runners)}})
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20)
            except asyncio.TimeoutError:
                msg = {"type": "ping"}
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(LIVE_CHANNEL, q)
