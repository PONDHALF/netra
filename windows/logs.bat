@echo off
cd /d "%~dp0\.."
echo Press Ctrl+C to exit
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs -f --tail 200
