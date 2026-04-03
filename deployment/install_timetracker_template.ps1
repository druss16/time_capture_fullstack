# install_timetracker_template.ps1
# ============================================================
# TimeTracker Deployment Script - FIRM_NAME
# ============================================================
#
# BEFORE SENDING TO CLIENT IT:
#   1. Copy this file and rename: install_timetracker_FIRMSLUG.ps1
#   2. Replace REPLACE_WITH_ORG_TOKEN with the client's org token
#      (found in TimeTracker admin dashboard → Org Settings)
#   3. Place this script and TimeTracker-Windows-Setup.exe on a network share
#
# HOW IT DEPLOYS:
#   - Add as a GPO Logon script (NOT Startup)
#   - Path: User Configuration → Policies → Windows Settings → Scripts → Logon
#   - Safe to re-run — skips machines already installed
# ============================================================

# ── Step 1: Write deploy.json to ProgramData (machine-wide, readable by all users) ──
$configDir = "$env:PROGRAMDATA\TimeTracker"
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}
$config = @{
    org_token  = "REPLACE_WITH_ORG_TOKEN"
    server_url = "https://timetracker-api-k375.onrender.com"
} | ConvertTo-Json
Set-Content -Path "$configDir\deploy.json" -Value $config -Force
Write-Host "Config written to $configDir\deploy.json"

# ── Step 2: Install TimeTracker (skip if already installed) ──
$installPath = "$env:LOCALAPPDATA\TimeTracker\TimeTrackerAgent.exe"
if (Test-Path $installPath) {
    Write-Host "TimeTracker already installed, skipping."
    exit 0
}

# Get the directory this script is running from (network share)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $scriptDir "TimeTracker-Windows-Setup.exe"
if (-not (Test-Path $installer)) {
    Write-Host "ERROR: TimeTracker-Windows-Setup.exe not found at $installer"
    exit 1
}

# Copy to local temp and install silently
Copy-Item $installer "$env:TEMP\TimeTrackerSetup.exe" -Force
Start-Process -FilePath "$env:TEMP\TimeTrackerSetup.exe" -ArgumentList "/VERYSILENT", "/NORESTART" -Wait
Remove-Item "$env:TEMP\TimeTrackerSetup.exe" -Force -ErrorAction SilentlyContinue
Write-Host "TimeTracker installed successfully."