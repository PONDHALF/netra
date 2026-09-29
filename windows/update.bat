@echo off
cd /d "%~dp0\.."
docker info >nul 2>&1
if errorlevel 1 ( echo [ERROR] Docker engine is not running - open Docker Desktop and wait for "Engine running" & pause & exit /b 1 )
echo === NETRA: pulling latest code from GitHub and rebuilding ===
git pull
if errorlevel 1 ( echo [ERROR] git pull failed & pause & exit /b 1 )
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
pause
