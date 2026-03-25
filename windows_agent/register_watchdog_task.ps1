# register_watchdog_task.ps1
# Generic — no customization needed per firm.
# Deploy as a GPO Logon script alongside install_timetracker.ps1
#
# What it does:
#   - Checks if tt_watchdog.exe is installed
#   - Checks if the watchdog task is already registered
#   - If not, registers it via Task Scheduler
#   - Runs silently — safe to re-run on every logon

$watchdogExe = "$env:LOCALAPPDATA\TimeTracker\tt_watchdog.exe"

# Nothing to do if watchdog isn't installed yet
if (-not (Test-Path $watchdogExe)) {
    exit 0
}

# Already registered — nothing to do
$existing = schtasks /Query /TN "TimeTrackerWatchdog" 2>&1
if ($LASTEXITCODE -eq 0) {
    exit 0
}

$xml = @"
<?xml version="1.0"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>MavOps TimeTracker Watchdog - restarts agent if it stops or freezes</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </LogonTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT5M</Interval>
        <Duration>P9999D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <Enabled>true</Enabled>
      <StartBoundary>2024-01-01T00:00:00</StartBoundary>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions>
    <Exec>
      <Command>$watchdogExe</Command>
    </Exec>
  </Actions>
</Task>
"@

$tmpXml = "$env:TEMP\tt_watchdog_task.xml"
$xml | Set-Content -Path $tmpXml -Encoding UTF8
schtasks /Create /TN "TimeTrackerWatchdog" /XML $tmpXml /F
Remove-Item $tmpXml -ErrorAction SilentlyContinue