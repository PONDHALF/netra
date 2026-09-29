# ---------- 1) build หน้าเว็บ
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 2) backend + engine
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 fonts-thai-tlwg fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# CPU เป็นค่าเริ่มต้น — เครื่องที่มี NVIDIA ใช้ docker-compose.gpu.yml (TORCH_INDEX=.../cu124)
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch torchvision --index-url ${TORCH_INDEX}
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/ engine/
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist

ENV NETRA_DATA=/app/data \
    EASYOCR_MODULE_PATH=/app/data/.cache/easyocr \
    YOLO_CONFIG_DIR=/app/data/.cache/ultralytics \
    HF_HOME=/app/data/.cache/huggingface \
    PYTHONUNBUFFERED=1
EXPOSE 8000
# ดาวน์โหลดโมเดลป้ายไทยตอนเริ่ม (ข้ามถ้ามีแล้ว) — ถ้าออฟไลน์ก็ยังเปิดระบบได้ในโหมดสำรอง
CMD ["sh", "-c", "python -m engine.fetch_models $([ \"$NETRA_TYPHOON\" = 1 ] && echo --typhoon); exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
