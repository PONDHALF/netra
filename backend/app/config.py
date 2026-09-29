from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("NETRA_DATA", ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
CORRECTIONS_DIR = DATA_DIR / "corrections"
DATABASE_URL = os.getenv("NETRA_DB", f"sqlite:///{DATA_DIR / 'netra.db'}")
FRONTEND_DIST = Path(os.getenv("NETRA_FRONTEND", ROOT / "frontend" / "dist"))
ALLOWED_EXT = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".ts"}
PRELOAD_ENGINE = os.getenv("NETRA_PRELOAD", "1") == "1"

for d in (UPLOAD_DIR, OUTPUT_DIR, CORRECTIONS_DIR):
    d.mkdir(parents=True, exist_ok=True)
