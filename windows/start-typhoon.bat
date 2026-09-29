@echo off
cd /d "%~dp0\.."
echo === NETRA: starting with Typhoon OCR 3B (first run downloads ~7.5 GB) ===
set NETRA_TYPHOON=1
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
if errorlevel 1 ( pause & exit /b 1 )
start http://localhost:8000
pause
