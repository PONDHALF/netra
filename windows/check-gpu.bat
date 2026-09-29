@echo off
echo === Step 1: is Docker Desktop running? ===
docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker engine is not running.
  echo   1. Open "Docker Desktop" from the Start menu
  echo   2. Wait until it shows "Engine running" ^(green, bottom-left^)
  echo   3. Run this file again
  echo If it never starts: run "wsl --install" and "wsl --update" as Administrator, then reboot.
  pause
  exit /b 1
)
echo OK - Docker is running
echo.
echo === Step 2: can Docker see the NVIDIA GPU? ===
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
if errorlevel 1 (
  echo [ERROR] Docker is running but cannot see the GPU.
  echo   - Update the NVIDIA driver and reboot
  echo   - Docker Desktop: Settings - General - enable "Use the WSL 2 based engine"
) else (
  echo.
  echo OK - GPU is visible. Next: double-click start-typhoon.bat
)
pause
