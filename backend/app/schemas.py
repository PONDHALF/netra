from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


def media_url(rel: str | None) -> str | None:
    return f"/media/{rel}" if rel else None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str
    location: str | None
    created_at: datetime


class JobStats(BaseModel):
    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    plates_read: int = 0
    corrected: int = 0


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: SourceOut
    original_name: str
    status: str
    progress: float
    stage: str | None
    eta_sec: float | None
    error: str | None
    video_start: datetime | None
    duration_sec: float | None
    summary: dict | None
    use_typhoon: bool = False
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    output_path: str | None = Field(exclude=True)
    thumb_path: str | None = Field(exclude=True)
    file_path: str = Field(exclude=True)
    stats: JobStats | None = None

    @computed_field
    def video_url(self) -> str | None:
        return media_url(self.output_path)

    @computed_field
    def source_video_url(self) -> str | None:
        return media_url(self.file_path)

    @computed_field
    def thumb_url(self) -> str | None:
        return media_url(self.thumb_path)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    job_id: int | None
    track_id: int
    ts: datetime
    video_offset_sec: float | None
    first_seen_sec: float | None
    last_seen_sec: float | None
    vehicle_type: str
    vehicle_conf: float
    plate_text: str | None
    plate_province: str | None
    plate_conf: float
    plate_valid: bool
    ocr_raw: str | None
    ocr_engine: str | None = None
    is_corrected: bool
    original_plate_text: str | None
    original_plate_province: str | None
    corrected_at: datetime | None
    car_img: str | None = Field(exclude=True)
    plate_img: str | None = Field(exclude=True)
    source_name: str | None = None

    @computed_field
    def car_img_url(self) -> str | None:
        return media_url(self.car_img)

    @computed_field
    def plate_img_url(self) -> str | None:
        return media_url(self.plate_img)


class EventPage(BaseModel):
    items: list[EventOut]
    total: int


class EventPatch(BaseModel):
    plate_text: str | None = Field(default=None, max_length=20)
    plate_province: str | None = Field(default=None, max_length=50)
    vehicle_type: str | None = None
