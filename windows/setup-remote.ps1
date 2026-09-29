# NETRA - one-time setup so the Mac can deploy over SSH through Tailscale.
# Run in PowerShell as Administrator (safe to run again):
#   powershell -ExecutionPolicy Bypass -File <repo>\windows\setup-remote.ps1 -PublicKey "ssh-ed25519 AAAA... mac"
param(
    [Parameter(Mandatory = $true)][string]$PublicKey,
    [string]$RepoDir = ""
)
$ErrorActionPreference = "Stop"
# The repo is the parent folder of this script (works wherever it was cloned)
if (-not $RepoDir) { $RepoDir = Split-Path -Parent $PSScriptRoot }

# Windows PowerShell 5.1 turns anything a native program writes to stderr into a fatal error
# under "Stop" (ssh-keyscan and git print progress there) - run them through cmd instead.
function Invoke-Native([string]$CommandLine) {
    cmd /c "$CommandLine 2>nul"
    if ($LASTEXITCODE -ne 0) { Write-Host "[WARN] exit $LASTEXITCODE : $CommandLine" -ForegroundColor Yellow }
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Host "[ERROR] Run PowerShell as Administrator." -ForegroundColor Red; exit 1 }

Write-Host "== 1/6 OpenSSH Server ==" -ForegroundColor Cyan
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*"
if ($cap.State -ne "Installed") { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Write-Host "sshd running"

Write-Host "== 2/6 Allow the Mac's SSH key ==" -ForegroundColor Cyan
# Administrators use a shared file that must be readable only by Administrators and SYSTEM
$adminKeys = "C:\ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $adminKeys) -or -not (Select-String -Path $adminKeys -SimpleMatch $PublicKey -Quiet)) {
    Add-Content -Path $adminKeys -Value $PublicKey -Encoding ascii
}
icacls $adminKeys /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F" | Out-Null
$userSsh = Join-Path $env:USERPROFILE ".ssh"
New-Item -ItemType Directory -Force -Path $userSsh | Out-Null
$userKeys = Join-Path $userSsh "authorized_keys"
if (-not (Test-Path $userKeys) -or -not (Select-String -Path $userKeys -SimpleMatch $PublicKey -Quiet)) {
    Add-Content -Path $userKeys -Value $PublicKey -Encoding ascii
}
Write-Host "key installed"

Write-Host "== 3/6 Firewall: SSH and NETRA web only from Tailscale (100.64.0.0/10) ==" -ForegroundColor Cyan
Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue | Disable-NetFirewallRule
foreach ($r in @(@{Name = "NETRA-SSH-Tailscale"; Port = 22}, @{Name = "NETRA-Web-Tailscale"; Port = 8000})) {
    Remove-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name $r.Name -DisplayName $r.Name -Direction Inbound -Protocol TCP `
        -LocalPort $r.Port -RemoteAddress "100.64.0.0/10" -Action Allow -Profile Any | Out-Null
}
Write-Host "ports 22 and 8000 open to Tailscale devices only"

Write-Host "== 4/6 Read-only GitHub deploy key (so git pull works over SSH) ==" -ForegroundColor Cyan
$deployKey = Join-Path $userSsh "netra_deploy"
if (-not (Test-Path $deployKey)) {
    Invoke-Native "ssh-keygen -t ed25519 -f `"$deployKey`" -N `"`" -q -C netra-windows"
}
$sshConfig = Join-Path $userSsh "config"
if (-not (Test-Path $sshConfig) -or -not (Select-String -Path $sshConfig -SimpleMatch "netra_deploy" -Quiet)) {
    Add-Content -Path $sshConfig -Encoding ascii -Value "`nHost github.com`n  IdentityFile ~/.ssh/netra_deploy`n  IdentitiesOnly yes"
}
$knownHosts = Join-Path $userSsh "known_hosts"
# GitHub's published ed25519 host key (https://api.github.com/meta, SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU)
# - pinned instead of ssh-keyscan, which can be spoofed and failed silently on some machines
$githubKey = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
if (-not (Test-Path $knownHosts) -or -not (Select-String -Path $knownHosts -SimpleMatch "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" -Quiet)) {
    Add-Content -Path $knownHosts -Value $githubKey -Encoding ascii
}
if (Test-Path (Join-Path $RepoDir ".git")) {
    Invoke-Native "git -C `"$RepoDir`" remote set-url origin git@github.com:PONDHALF/netra.git"
    Write-Host "repo remote switched to SSH"
}

Write-Host "== 5/6 Keep Typhoon on across deploys ==" -ForegroundColor Cyan
$envFile = Join-Path $RepoDir ".env"
if (-not (Test-Path $envFile)) { Set-Content -Path $envFile -Value "NETRA_TYPHOON=1" -Encoding ascii }
Get-Content $envFile

Write-Host "== 6/6 Scheduled task NETRA-Deploy (make deploy on the Mac starts it) ==" -ForegroundColor Cyan
# Docker builds over SSH cannot read the Windows credential store, so the Mac triggers this task,
# which runs deploy-task.bat inside the logged-in desktop session instead.
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ("/c `"" + (Join-Path $RepoDir "windows\deploy-task.bat") + "`"")
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "NETRA-Deploy" -Action $action -Principal $principal -Settings $settings -Force | Out-Null
# Restart Docker Desktop + WSL from the Mac (make remote-restart-docker) - applies .wslconfig changes
$rAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"" + (Join-Path $RepoDir "windows\restart-docker.ps1") + "`"")
Register-ScheduledTask -TaskName "NETRA-RestartDocker" -Action $rAction -Principal $principal -Force | Out-Null
Write-Host "tasks registered (NETRA-Deploy, NETRA-RestartDocker)"

$tsIp = ""
try { $tsIp = (Invoke-Native "tailscale ip -4" | Select-Object -First 1) } catch {}
Write-Host ""
Write-Host "================ DONE - send these to the Mac ================" -ForegroundColor Green
Write-Host ("WIN_HOST = " + $(if ($tsIp) { $tsIp } else { "(Tailscale not running - start it and run: tailscale ip -4)" }))
Write-Host ("WIN_USER = " + $env:USERNAME)
Write-Host ("WIN_DIR  = " + $RepoDir)
Write-Host "Reminders: Docker Desktop -> Settings -> General -> 'Start Docker Desktop when you sign in'"
Write-Host "           Windows power settings -> never sleep (deploys fail while asleep)"
