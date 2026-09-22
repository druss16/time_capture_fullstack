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

# ── Step 5: Force-install the "TimeTracker URL Reporter" browser extension ──
# Silently installs and pins the extension via browser policy so no user action
# is needed. Finds a free numeric slot per browser so it never clobbers another
# IT-managed extension, and is idempotent on re-runs. Uses the elevated (HKLM)
# context the installer already runs in.
#
# BOTH BROWSERS, AND THE IDS ARE DIFFERENT. The same source zip published to
# two stores gets two unrelated extension ids, so each policy needs its own id
# paired with its own update URL. Only Edge was covered before, which meant
# every Chrome user silently fell back to title-only matching — and the
# clio_anchor attribution tier, which reads the matter id straight out of the
# tab URL, could not fire for them at all. Lawyers skew Chrome.
#
# A wrong id here fails SILENTLY: the policy is written, Chrome finds no such
# extension, and nothing reports it. The Chrome id below was verified against
# the live listing (chromewebstore.google.com/detail/<id> → "TimeTracker URL
# Reporter", publisher Mavops) rather than assumed from the Edge one.
$ttBrowsers = @(
    @{
        Name  = "Edge"
        ExtId = "bnnifiompbeebhapoojlonamdghmlifh"
        Crx   = "https://edge.microsoft.com/extensionwebstorebase/v1/crx"
        Path  = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist"
    },
    @{
        Name  = "Chrome"
        ExtId = "ophdgbaogdhfdhmfnnjniegccekmgfok"
        Crx   = "https://clients2.google.com/service/update2/crx"
        Path  = "HKLM:\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist"
    }
)

foreach ($b in $ttBrowsers) {
    try {
        if (-not (Test-Path $b.Path)) { New-Item -Path $b.Path -Force | Out-Null }
        $ttProps   = @((Get-Item $b.Path).Property)
        $ttAlready = $ttProps | Where-Object {
            (Get-ItemProperty -Path $b.Path -Name $_).$_ -like "$($b.ExtId);*"
        }
        if ($ttAlready) {
            Write-Host "TimeTracker extension already force-listed for $($b.Name)."
        } else {
            $ttUsed = @($ttProps | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
            $ttSlot = 1; while ($ttUsed -contains $ttSlot) { $ttSlot++ }
            New-ItemProperty -Path $b.Path -Name "$ttSlot" `
                -Value "$($b.ExtId);$($b.Crx)" -PropertyType String -Force | Out-Null
            Write-Host "Force-installed TimeTracker extension for $($b.Name) [slot $ttSlot]."
        }
    } catch {
        # Per-browser: a machine without Chrome must not stop Edge being set up.
        Write-Host "WARN: could not set $($b.Name) force-install policy: $_"
    }
}

Write-Host "TimeTracker deployment complete."