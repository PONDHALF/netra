"""Schema ออกแบบให้ใช้ต่อใน Phase 2 (sources.type = video | camera)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now()


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="video")  # video | camera
    location: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))                 # กล้อง: rtsp://… / http://… / 0 (webcam) / ไฟล์
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)         # กล้อง: เริ่มเองตอนเปิดระบบ
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    jobs: Mapped[list[Job]] = relationship(back_populates="source")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(500))          # สัมพัทธ์กับ DATA_DIR
    original_name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|processing|done|failed|cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(20))
    eta_sec: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    video_start: Mapped[datetime | None] = mapped_column(DateTime)  # เวลาจริงของเฟรมแรก
    duration_sec: Mapped[float | None] = mapped_column(Float)
    output_path: Mapped[str | None] = mapped_column(String(500))
    thumb_path: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[dict | None] = mapped_column(JSON)
    use_typhoon: Mapped[bool] = mapped_column(Boolean, default=False)   # อ่านป้ายซ้ำด้วย Typhoon OCR 3B
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    source: Mapped[Source] = relationship(back_populates="jobs", lazy="joined")
    events: Mapped[list[Event]] = relationship(back_populates="job", cascade="all, delete-orphan",
                                               passive_deletes=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)         # เวลาจริง
    video_offset_sec: Mapped[float | None] = mapped_column(Float)
    first_seen_sec: Mapped[float | None] = mapped_column(Float)
    last_seen_sec: Mapped[float | None] = mapped_column(Float)
    vehicle_type: Mapped[str] = mapped_column(String(20), index=True)
    vehicle_conf: Mapped[float] = mapped_column(Float, default=0.0)
    plate_text: Mapped[str | None] = mapped_column(String(20), index=True)
    plate_province: Mapped[str | None] = mapped_column(String(50))
    plate_conf: Mapped[float] = mapped_column(Float, default=0.0)
    plate_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    car_img: Mapped[str | None] = mapped_column(String(500))
    plate_img: Mapped[str | None] = mapped_column(String(500))
    ocr_raw: Mapped[str | None] = mapped_column(Text)
    ocr_engine: Mapped[str | None] = mapped_column(String(20))           # char-ocr | easyocr | typhoon
    is_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    original_plate_text: Mapped[str | None] = mapped_column(String(20))
    original_plate_province: Mapped[str | None] = mapped_column(String(50))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    job: Mapped[Job | None] = relationship(back_populates="events")
    source: Mapped[Source] = relationship(lazy="joined")

    __table_args__ = (Index("ix_events_job_offset", "job_id", "video_offset_sec"),)
