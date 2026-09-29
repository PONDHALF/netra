# Restart Docker Desktop + WSL (applies %USERPROFILE%\.wslconfig, e.g. a new memory limit).
# Run by the "NETRA-RestartDocker" scheduled task (desktop session) - from the Mac: make remote-restart-docker
$log = Join-Path (Split-Path -Parent $PSScriptRoot) "data\restart-docker.log"
"[restart] $(Get-Date)" | Out-File $log -Encoding ascii
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5
wsl --shutdown
Start-Sleep -Seconds 8
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { "[restart] docker ready after $(($i + 1) * 5)s" | Out-File $log -Append -Encoding ascii; break }
}
docker info --format "mem={{.MemTotal}}" 2>&1 | Out-File $log -Append -Encoding ascii
"RESTART-DONE" | Out-File $log -Append -Encoding ascii
