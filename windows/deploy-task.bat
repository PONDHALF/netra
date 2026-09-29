@echo off
rem NETRA deploy - run by the "NETRA-Deploy" scheduled task (started from the Mac with: make deploy).
rem Runs inside the logged-in desktop session so Docker can read its credential store
rem (docker build over SSH fails with "A specified logon session does not exist").
cd /d "%~dp0\.."
if not exist data mkdir data
> data\deploy.log echo [deploy] %date% %time% on %COMPUTERNAME%
>> data\deploy.log echo [deploy] git pull
git pull --ff-only >> data\deploy.log 2>&1 || goto :fail
>> data\deploy.log echo [deploy] docker compose up --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build >> data\deploy.log 2>&1 || goto :fail
>> data\deploy.log echo DEPLOY-EXIT=0
exit /b 0
:fail
>> data\deploy.log echo DEPLOY-EXIT=1
exit /b 1
