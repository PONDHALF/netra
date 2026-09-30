@echo off
rem NETRA deploy - run by the "NETRA-Deploy" scheduled task (started from the Mac with: make deploy).
rem Runs inside the logged-in desktop session so Docker can read its credential store
rem (docker build over SSH fails with "A specified logon session does not exist").
rem While PlateNet training runs (container netra-train), only build - do not start Live (netra + camsim).
cd /d "%~dp0\.."
if not exist data mkdir data
> data\deploy.log echo [deploy %time%] start on %COMPUTERNAME%
>> data\deploy.log echo [deploy %time%] git pull
git pull --ff-only >> data\deploy.log 2>&1 || goto :fail
set TRAINING=
for /f %%i in ('docker ps -q -f "name=^netra-train$" -f "status=running"') do set TRAINING=1
if defined TRAINING goto :build_only
>> data\deploy.log echo [deploy %time%] docker compose up --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build >> data\deploy.log 2>&1 || goto :fail
goto :done
:build_only
>> data\deploy.log echo [deploy %time%] training is running - build only, Live stays stopped
docker compose -f docker-compose.yml -f docker-compose.gpu.yml build netra >> data\deploy.log 2>&1 || goto :fail
:done
>> data\deploy.log echo [deploy %time%] done
>> data\deploy.log echo DEPLOY-EXIT=0
exit /b 0
:fail
>> data\deploy.log echo DEPLOY-EXIT=1
exit /b 1
