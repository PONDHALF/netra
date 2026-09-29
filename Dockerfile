# syntax=docker/dockerfile:1
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
# cache mount: ไฟล์ที่โหลดแล้วเก็บไว้ข้าม build — ถ้าเน็ตหลุดกลางทาง รอบถัดไปไม่ต้องโหลดใหม่ทั้งหมด (~3 GB)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 torch torchvision --index-url ${TORCH_INDEX}
# TensorRT (เฉพาะ image สำหรับการ์ด NVIDIA — docker-compose.gpu.yml ตั้ง INSTALL_TRT=1)
# ทำให้ YOLO เร็วขึ้นหลายเท่าบนเครื่องที่ CPU ช้า — engine/trt.py แปลงโมเดลให้อัตโนมัติตอนเริ่มครั้งแรก
ARG INSTALL_TRT=0
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_TRT" = "1" ]; then \
      pip install --retries 10 --timeout 120 "tensorrt-cu12" "onnx>=1.12.0" "onnxslim>=0.1.71"; \
    fi
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 -r requirements.txt

COPY engine/ engine/
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
COPY docker/entrypoint.sh docker/entrypoint.sh

ENV NETRA_DATA=/app/data \
    EASYOCR_MODULE_PATH=/cache/easyocr \
    YOLO_CONFIG_DIR=/cache/ultralytics \
    HF_HOME=/cache/huggingface \
    PYTHONUNBUFFERED=1
EXPOSE 8000
# ย้าย cache (ครั้งเดียว) + ดาวน์โหลดโมเดลตอนเริ่ม แล้วเปิดเซิร์ฟเวอร์ — ดู docker/entrypoint.sh
CMD ["sh", "docker/entrypoint.sh"]
