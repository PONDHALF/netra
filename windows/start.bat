@echo off
cd /d "%~dp0\.."
docker info >nul 2>&1
if errorlevel 1 ( echo [ERROR] Docker engine is not running - open Docker Desktop and wait for "Engine running" & pause & exit /b 1 )
echo === NETRA: starting (NVIDIA GPU) ===
echo First run takes a while: building image + downloading models
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
if errorlevel 1 (
  echo [ERROR] Make sure Docker Desktop is running
  pause
  exit /b 1
)
echo Open http://localhost:8000
start http://localhost:8000
pause
