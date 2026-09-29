@echo off
cd /d "%~dp0\.."
echo === NETRA: pulling latest code from GitHub and rebuilding ===
git pull
if errorlevel 1 ( echo [ERROR] git pull failed & pause & exit /b 1 )
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
pause
