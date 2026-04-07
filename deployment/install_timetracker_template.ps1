# install_timetracker_FIRMSLUG.ps1
# ============================================================
# TimeTracker Deployment — FIRM_NAME
# GPO: User Configuration → Windows Settings → Scripts → Logon
# ============================================================

# ── Step 1: Write org token to ProgramData ──
$configDir = "$env:PROGRAMDATA\TimeTracker"
if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir -Force | Out-Null }
$config = @{ org_token = "REPLACE_WITH_ORG_TOKEN"; server_url = "https://timetracker-api-k375.onrender.com" } | ConvertTo-Json
Set-Content -Path "$configDir\deploy.json" -Value $config -Force

# ── Step 2: Install agent (skip if already installed) ──
$installPath = "$env:LOCALAPPDATA\TimeTracker\TimeTrackerAgent.exe"
if (-not (Test-Path $installPath)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $installer = Join-Path $scriptDir "TimeTracker-Windows-Setup.exe"
    if (-not (Test-Path $installer)) { Write-Host "ERROR: Installer not found at $installer"; exit 1 }
    Copy-Item $installer "$env:TEMP\TimeTrackerSetup.exe" -Force
    Start-Process -FilePath "$env:TEMP\TimeTrackerSetup.exe" -ArgumentList "/VERYSILENT", "/NORESTART" -Wait
    Remove-Item "$env:TEMP\TimeTrackerSetup.exe" -Force -ErrorAction SilentlyContinue
    Write-Host "TimeTracker installed."
} else {
    Write-Host "TimeTracker already installed — skipping."
}

# ── Step 3: Register Task Scheduler tasks ──
$watchdogExe = "$env:LOCALAPPDATA\TimeTracker\tt_watchdog.exe"
$agentExe    = "$env:LOCALAPPDATA\TimeTracker\TimeTrackerAgent.exe"

$existingWatchdog = schtasks /Query /TN "TimeTrackerWatchdog" 2>&1
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $watchdogExe) {
        schtasks /Create /TN "TimeTrackerWatchdog" /TR "`"$watchdogExe`"" /SC ONLOGON /RL LIMITED /F | Out-Null
        Write-Host "Registered TimeTrackerWatchdog task."
    }
} else { Write-Host "TimeTrackerWatchdog already registered." }

$existingAgent = schtasks /Query /TN "TimeTrackerAgent" 2>&1
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $agentExe) {
        schtasks /Create /TN "TimeTrackerAgent" /TR "`"$agentExe`"" /SC ONLOGON /RL LIMITED /F | Out-Null
        Write-Host "Registered TimeTrackerAgent task."
    }
} else { Write-Host "TimeTrackerAgent already registered." }

# ── Step 4: Start watchdog if not running ──
$running = Get-Process tt_watchdog -ErrorAction SilentlyContinue
if (-not $running -and (Test-Path $watchdogExe)) {
    Start-Process $watchdogExe
    Write-Host "Started tt_watchdog.exe"
}

Write-Host "TimeTracker deployment complete."