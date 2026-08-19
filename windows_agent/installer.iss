; TimeTracker Windows Installer Script
; Inno Setup 6.x
;
; ENTERPRISE DEPLOYMENT:
;   TimeTracker-Windows-Setup.exe /VERYSILENT /ORG_TOKEN=ODT-XKCD-9F3A
;
; IT admins pass the org token as a command-line parameter.
; The installer writes it to %USERPROFILE%\.timetracker\config.json
; so the agent auto-pairs on first boot.

#define MyAppName "TimeTracker"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "MavOps"
#define MyAppURL "https://github.com/druss16/timetracker-releases"
#define MyAppExeName "TimeTracker.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Install to localappdata
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Output settings
OutputDir=Output
OutputBaseFilename=TimeTracker-Windows-Setup

; Compression
Compression=lzma
SolidCompression=yes

; Windows version requirement
MinVersion=10.0

; Installer appearance
SetupIconFile=timetracker.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

; Privileges - install for current user only
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Close running apps
CloseApplications=force
CloseApplicationsFilter=TimeTracker*.exe,TimeTrackerAgent*.exe,tt_watchdog.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "cleaninstall"; Description: "Fresh install (clear all saved settings and pairing data)"; GroupDescription: "Install Options:"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}"

[Files]
Source: "dist\TimeTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\TimeTrackerAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\tt_watchdog.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "timetracker.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\timetracker.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\timetracker.ico"; Tasks: desktopicon

; IMPORTANT:
; Removed HKCU Run key startup entry.
; Startup is now installer-managed via the main scheduled task only.

[Run]
Filename: "{app}\tt_watchdog.exe"; Flags: nowait postinstall runhidden
Filename: "{app}\TimeTrackerAgent.exe"; Description: "Start TimeTracker"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; v1.3.22: Use cmd.exe /c taskkill instead of the agent .exe.
; The agent has a single-instance mutex check, so launching it with
; --unregister-task would silently exit (the running instance holds
; the mutex). This bypasses that entirely. Real cleanup happens in
; CurUninstallStepChanged(usUninstall) below.
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM tt_watchdog.exe /T"; Flags: runhidden; RunOnceId: "KillWatchdog"
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM TimeTrackerAgent.exe /T"; Flags: runhidden; RunOnceId: "KillAgent"
Filename: "{cmd}"; Parameters: "/c taskkill /F /IM TimeTracker.exe /T"; Flags: runhidden; RunOnceId: "KillGui"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{localappdata}\Programs\TimeTracker"

[Code]

// ── Global variables ──
var
  ConfigBackupPath: String;
  ConfigBackedUp: Boolean;
  DeviceIdBackupPath: String;
  DeviceIdBackedUp: Boolean;


// ═══════════════════════════════════════════════════════════════
// ORG_TOKEN SUPPORT — Enterprise silent deployment
// ═══════════════════════════════════════════════════════════════

function GetOrgToken(): String;
var
  I: Integer;
  Param: String;
begin
  Result := '';
  for I := 1 to ParamCount do begin
    Param := ParamStr(I);
    if (Pos('/ORG_TOKEN=', UpperCase(Param)) = 1) or
       (Pos('/org_token=', LowerCase(Param)) = 1) then begin
      Result := Copy(Param, Length('/ORG_TOKEN=') + 1, MaxInt);
      Log('Found ORG_TOKEN parameter: ' + Result);
      Break;
    end;
  end;
end;

procedure WriteOrgTokenToConfig();
var
  UserProfile: String;
  ConfigDir: String;
  ConfigPath: String;
  OrgToken: String;
  ConfigContent: String;
  ExistingContent: AnsiString;
begin
  OrgToken := GetOrgToken();
  if OrgToken = '' then begin
    Log('No ORG_TOKEN provided — skipping enterprise config');
    Exit;
  end;

  UserProfile := GetEnv('USERPROFILE');
  ConfigDir := UserProfile + '\.timetracker';
  ConfigPath := ConfigDir + '\config.json';

  if not DirExists(ConfigDir) then
    ForceDirectories(ConfigDir);

  if FileExists(ConfigPath) then begin
    if LoadStringFromFile(ConfigPath, ExistingContent) then begin
      if Pos('"api_key"', String(ExistingContent)) > 0 then begin
        Log('config.json already has api_key — device already paired, skipping org_token write');
        Exit;
      end;
    end;
  end;

  ConfigContent :=
    '{' + #13#10 +
    '  "org_token": "' + OrgToken + '",' + #13#10 +
    '  "api_base": "https://timetracker.mavops.ai"' + #13#10 +
    '}';

  if SaveStringToFile(ConfigPath, ConfigContent, False) then
    Log('Wrote org_token to ' + ConfigPath)
  else
    Log('WARNING: Failed to write org_token to config.json');
end;


// ═══════════════════════════════════════════════════════════════
// Task Scheduler: main startup task only
// ═══════════════════════════════════════════════════════════════

procedure CreateScheduledTask;
var
  ResultCode: Integer;
  AgentPath: String;
  XmlPath: String;
  XmlContent: String;
begin
  AgentPath := ExpandConstant('{app}\TimeTrackerAgent.exe');
  XmlPath := ExpandConstant('{tmp}\timetracker_task.xml');

  XmlContent :=
    '<?xml version="1.0"?>' + #13#10 +
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' + #13#10 +
    '  <RegistrationInfo>' + #13#10 +
    '    <Description>MavOps TimeTracker Agent - runs in background, auto-restarts on crash</Description>' + #13#10 +
    '  </RegistrationInfo>' + #13#10 +
    '  <Triggers>' + #13#10 +
    '    <LogonTrigger>' + #13#10 +
    '      <Enabled>true</Enabled>' + #13#10 +
    '      <Delay>PT5S</Delay>' + #13#10 +
    '    </LogonTrigger>' + #13#10 +
    '  </Triggers>' + #13#10 +
    '  <Principals>' + #13#10 +
    '    <Principal id="Author">' + #13#10 +
    '      <LogonType>InteractiveToken</LogonType>' + #13#10 +
    '      <RunLevel>HighestAvailable</RunLevel>' + #13#10 +
    '    </Principal>' + #13#10 +
    '  </Principals>' + #13#10 +
    '  <Settings>' + #13#10 +
    '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>' + #13#10 +
    '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>' + #13#10 +
    '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>' + #13#10 +
    '    <AllowHardTerminate>true</AllowHardTerminate>' + #13#10 +
    '    <StartWhenAvailable>true</StartWhenAvailable>' + #13#10 +
    '    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>' + #13#10 +
    '    <AllowStartOnDemand>true</AllowStartOnDemand>' + #13#10 +
    '    <Enabled>true</Enabled>' + #13#10 +
    '    <Hidden>false</Hidden>' + #13#10 +
    '    <RunOnlyIfIdle>false</RunOnlyIfIdle>' + #13#10 +
    '    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>' + #13#10 +
    '    <RestartOnFailure>' + #13#10 +
    '      <Interval>PT30S</Interval>' + #13#10 +
    '      <Count>999</Count>' + #13#10 +
    '    </RestartOnFailure>' + #13#10 +
    '  </Settings>' + #13#10 +
    '  <Actions>' + #13#10 +
    '    <Exec>' + #13#10 +
    '      <Command>' + AgentPath + '</Command>' + #13#10 +
    '      <Arguments>start</Arguments>' + #13#10 +
    '    </Exec>' + #13#10 +
    '  </Actions>' + #13#10 +
    '</Task>';

  SaveStringToFile(XmlPath, XmlContent, False);

  Exec('schtasks.exe', '/delete /tn "MavOps TimeTracker" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  Exec('schtasks.exe',
       '/create /tn "MavOps TimeTracker" /xml "' + XmlPath + '" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if ResultCode = 0 then
    Log('Scheduled task created successfully')
  else
    Log('Scheduled task creation failed with code: ' + IntToStr(ResultCode));

  DeleteFile(XmlPath);
  DeleteFile(ExpandConstant('{userstartup}\TimeTracker Agent.lnk'));
end;

// v1.3.22: Removes ALL scheduled tasks the agent might have created
// (main, watchdog, startup) plus legacy startup shortcuts and registry keys.
procedure RemoveScheduledTask;
var
  ResultCode: Integer;
begin
  // Main scheduled task (created by installer)
  Exec('schtasks.exe', '/delete /tn "MavOps TimeTracker" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('Removed scheduled task: MavOps TimeTracker (code=' + IntToStr(ResultCode) + ')');

  // Watchdog task (created by tt_watchdog.py at runtime)
  Exec('schtasks.exe', '/delete /tn "TimeTrackerWatchdog" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('Removed scheduled task: TimeTrackerWatchdog (code=' + IntToStr(ResultCode) + ')');

  // Startup task (created by startup_task.py at runtime)
  Exec('schtasks.exe', '/delete /tn "TimeTrackerStartup" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('Removed scheduled task: TimeTrackerStartup (code=' + IntToStr(ResultCode) + ')');

  // Legacy startup shortcuts (in case created by older versions)
  DeleteFile(ExpandConstant('{userstartup}\TimeTracker Agent.lnk'));
  DeleteFile(ExpandConstant('{userstartup}\TimeTracker.lnk'));

  // Legacy HKCU Run keys (in case any old version registered them)
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'TimeTracker');
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'TimeTrackerAgent');
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MavOpsTimeTracker');
end;


// ═══════════════════════════════════════════════════════════════
// Config backup/restore
// ═══════════════════════════════════════════════════════════════

procedure BackupUserConfig();
var
  UserProfile: String;
  ConfigPath: String;
  DeviceIdPath: String;
  AppDataDeviceId: String;
begin
  UserProfile := GetEnv('USERPROFILE');
  ConfigBackupPath := UserProfile + '\.timetracker\.config_backup.json';
  DeviceIdBackupPath := UserProfile + '\.timetracker\.deviceid_backup.txt';

  ConfigPath := UserProfile + '\.timetracker\config.json';
  if FileExists(ConfigPath) then begin
    if FileCopy(ConfigPath, ConfigBackupPath, False) then begin
      ConfigBackedUp := True;
      Log('Backed up config.json to ' + ConfigBackupPath);
    end else
      Log('WARNING: Failed to backup config.json');
  end else
    Log('No config.json found at ' + ConfigPath);

  DeviceIdPath := UserProfile + '\.timetracker\.device_id';
  AppDataDeviceId := ExpandConstant('{userappdata}') + '\TimeTracker\.device_id';

  if FileExists(DeviceIdPath) then begin
    if FileCopy(DeviceIdPath, DeviceIdBackupPath, False) then begin
      DeviceIdBackedUp := True;
      Log('Backed up .device_id from ' + DeviceIdPath);
    end;
  end else if FileExists(AppDataDeviceId) then begin
    if FileCopy(AppDataDeviceId, DeviceIdBackupPath, False) then begin
      DeviceIdBackedUp := True;
      Log('Backed up .device_id from ' + AppDataDeviceId);
    end;
  end else
    Log('No .device_id found to backup');
end;


procedure RestoreUserConfig();
var
  UserProfile: String;
  ConfigDir: String;
  ConfigPath: String;
  DeviceIdPath: String;
begin
  if IsTaskSelected('cleaninstall') then begin
    Log('Clean install selected - skipping config restore');
    Exit;
  end;

  UserProfile := GetEnv('USERPROFILE');
  ConfigDir := UserProfile + '\.timetracker';
  ConfigPath := ConfigDir + '\config.json';
  DeviceIdPath := ConfigDir + '\.device_id';
  ConfigBackupPath := UserProfile + '\.timetracker\.config_backup.json';
  DeviceIdBackupPath := UserProfile + '\.timetracker\.deviceid_backup.txt';

  if not DirExists(ConfigDir) then
    ForceDirectories(ConfigDir);

  if ConfigBackedUp then begin
    if not FileExists(ConfigPath) then begin
      if FileCopy(ConfigBackupPath, ConfigPath, False) then
        Log('Restored config.json from backup')
      else
        Log('WARNING: Failed to restore config.json');
    end else
      Log('config.json already exists - skipping restore');
  end;

  if DeviceIdBackedUp then begin
    if not FileExists(DeviceIdPath) then begin
      if FileCopy(DeviceIdBackupPath, DeviceIdPath, False) then
        Log('Restored .device_id from backup')
      else
        Log('WARNING: Failed to restore .device_id');
    end else
      Log('.device_id already exists - skipping restore');
  end;
end;


// ═══════════════════════════════════════════════════════════════
// Cleanup procedures
// ═══════════════════════════════════════════════════════════════

procedure CleanupOldInstalls();
var
  ResultCode: Integer;
begin
  Exec('taskkill', '/F /IM TimeTracker.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill', '/F /IM TimeTrackerAgent.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill', '/F /IM tt_watchdog.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);

  if DirExists(ExpandConstant('{localappdata}\TimeTracker')) then
    DelTree(ExpandConstant('{localappdata}\TimeTracker'), True, True, True);

  if DirExists(ExpandConstant('{localappdata}\Programs\TimeTracker')) then
    DelTree(ExpandConstant('{localappdata}\Programs\TimeTracker'), True, True, True);
end;

procedure CleanupUserData();
var
  UserProfile: String;
  AppData: String;
begin
  UserProfile := GetEnv('USERPROFILE');
  AppData := ExpandConstant('{userappdata}');

  if DirExists(UserProfile + '\.timetracker') then
    DelTree(UserProfile + '\.timetracker', True, True, True);

  if DirExists(AppData + '\TimeTracker') then
    DelTree(AppData + '\TimeTracker', True, True, True);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  BackupUserConfig();
  CleanupOldInstalls();

  if IsTaskSelected('cleaninstall') then
    CleanupUserData();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    Exec('taskkill', '/F /IM TimeTracker.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill', '/F /IM TimeTrackerAgent.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill', '/F /IM tt_watchdog.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;

  if CurStep = ssPostInstall then begin
    RestoreUserConfig();
    WriteOrgTokenToConfig();
    CreateScheduledTask;
  end;
end;

// v1.3.22: KILL PROCESSES FIRST before files are removed.
// Original bug: Inno tried to delete agent .exe while it was still running,
// which silently failed. The agent kept running in memory, watchdog kept
// relaunching it, scheduled tasks were never removed, and the tray icon
// stayed visible. This now kills all three processes (in dependency order
// so the watchdog can't relaunch the agent) before any other uninstall step.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  // ── usUninstall fires BEFORE files are removed ──
  if CurUninstallStep = usUninstall then
  begin
    Log('Killing all TimeTracker processes before uninstall...');

    // Kill in dependency order: watchdog FIRST so it can't relaunch agent,
    // then agent, then GUI
    Exec('taskkill', '/F /IM tt_watchdog.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Log('Killed tt_watchdog.exe (code=' + IntToStr(ResultCode) + ')');

    Exec('taskkill', '/F /IM TimeTrackerAgent.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Log('Killed TimeTrackerAgent.exe (code=' + IntToStr(ResultCode) + ')');

    Exec('taskkill', '/F /IM TimeTracker.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Log('Killed TimeTracker.exe (code=' + IntToStr(ResultCode) + ')');

    // Wait for OS to fully release file handles before deletion proceeds
    Sleep(2000);

    // Remove scheduled tasks now (before files are gone)
    RemoveScheduledTask;
  end;

  // ── usPostUninstall fires AFTER files are removed ──
  if CurUninstallStep = usPostUninstall then
  begin
    // Restart Explorer to clear ghost system tray icons
    // (Windows leaves the icon image in the tray even after the process
    // dies; restarting Explorer is the only reliable way to remove it)
    Exec('taskkill', '/F /IM explorer.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
    Exec('explorer.exe', '', '', SW_SHOW, ewNoWait, ResultCode);

    // User data prompt
    if MsgBox('Do you want to remove all TimeTracker settings and data?', mbConfirmation, MB_YESNO) = IDYES then
      CleanupUserData();
  end;
end;