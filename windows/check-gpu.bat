@echo off
echo === Checking that Docker can see the NVIDIA GPU ===
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
if errorlevel 1 echo [ERROR] Docker cannot see the GPU - update the NVIDIA driver and enable the WSL2 backend in Docker Desktop
pause
