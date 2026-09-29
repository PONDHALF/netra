"""NETRA API — รัน:  uvicorn backend.app.main:app --reload   (จากโฟลเดอร์ราก)"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import DATA_DIR, FRONTEND_DIST, ROOT
from .db import Base, engine, ensure_columns, get_db
from .models import Source
from .routers import events, jobs
from .schemas import SourceOut
from .worker import hub, runner

if str(ROOT) not in sys.path:  # ให้ import engine/ ได้
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_columns()
    hub.loop = asyncio.get_running_loop()
    runner.start()
    yield
    runner.shutdown()


app = FastAPI(title="NETRA API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(jobs.router)
app.include_router(events.router)


def typhoon_available() -> bool:
    from engine.typhoon import is_available

    return is_available()


def typhoon_default() -> bool:
    from engine.config import EngineConfig

    return EngineConfig().typhoon


@app.get("/api/health")
def health():
    eng = runner._engine
    return {"ok": True, "engine_loaded": eng is not None,
            "device": eng.cfg.device if eng else None,
            "plate_model": eng.plates.available if eng else None,
            "plate_ocr_model": eng.reader.char is not None if eng else None,
            "typhoon_available": typhoon_available(),
            "typhoon_default": typhoon_default(),
            "typhoon_loaded": eng is not None and eng._typhoon is not None,
            "busy_job": runner.current}


@app.get("/api/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    return db.query(Source).order_by(Source.name).all()


@app.get("/api/meta")
def meta():
    from engine.postprocess import PROVINCES

    return {"provinces": PROVINCES,
            "vehicle_types": {"car": "รถยนต์", "motorcycle": "จักรยานยนต์", "bus": "รถบัส", "truck": "รถบรรทุก"}}


app.mount("/media", StaticFiles(directory=DATA_DIR), name="media")

# เสิร์ฟหน้าเว็บที่ build แล้ว (โหมด production / docker)
if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
