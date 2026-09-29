#!/bin/sh
# เริ่มระบบใน container: ย้าย cache เก่า (ครั้งเดียว) → ดาวน์โหลด/ตรวจโมเดล → เริ่มเซิร์ฟเวอร์
set -e

# cache โมเดลเคยอยู่ใน data/.cache (โฟลเดอร์ของ Windows ที่แชร์เข้ามา — อ่านช้ามาก: Typhoon โหลด 107 วินาที)
# ย้ายไป volume ของ Docker ครั้งเดียว แทนการดาวน์โหลดใหม่ 7.5 GB
if [ -d /app/data/.cache ] && [ ! -e /cache/.migrated ]; then
  echo "ย้าย cache โมเดลไป Docker volume (ครั้งเดียว อาจใช้เวลาสักครู่)..."
  cp -a /app/data/.cache/. /cache/ && rm -rf /app/data/.cache
fi
touch /cache/.migrated

if [ "$NETRA_TYPHOON" = "1" ]; then
  python -m engine.fetch_models --typhoon || echo "ดาวน์โหลดโมเดลไม่ครบ — ระบบยังเริ่มได้"
else
  python -m engine.fetch_models || echo "ดาวน์โหลดโมเดลไม่ครบ — ระบบยังเริ่มได้"
fi
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
