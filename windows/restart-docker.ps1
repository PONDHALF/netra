# Restart Docker Desktop + WSL (applies %USERPROFILE%\.wslconfig, e.g. a new memory limit).
# Run by the "NETRA-RestartDocker" scheduled task (desktop session) - from the Mac: make remote-restart-docker
$log = Join-Path (Split-Path -Parent $PSScriptRoot) "data\restart-docker.log"
"[restart] $(Get-Date)" | Out-File $log -Encoding ascii
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5
wsl --shutdown
Start-Sleep -Seconds 8
# Docker Desktop may be a per-user install (%LOCALAPPDATA%\Programs\DockerDesktop) or machine-wide
$exe = @("$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe", "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
"[restart] starting $exe" | Out-File $log -Append -Encoding ascii
Start-Process $exe
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { "[restart] docker ready after $(($i + 1) * 5)s" | Out-File $log -Append -Encoding ascii; break }
}
cmd /c "docker info --format mem={{.MemTotal}} 2>&1" | Out-File $log -Append -Encoding ascii
"RESTART-DONE" | Out-File $log -Append -Encoding ascii
