; TimeTracker Windows Installer Script
; Inno Setup 6.x

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
CloseApplicationsFilter=TimeTracker*.exe,TimeTrackerAgent*.exe
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
Source: "timetracker.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\timetracker.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\timetracker.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\TimeTrackerAgent.exe"; Description: "Start TimeTracker Agent"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\TimeTrackerAgent.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopAgent"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{localappdata}\Programs\TimeTracker"

[Code]

// ── Global variables for config backup/restore ──
var
  ConfigBackupPath: String;
  ConfigBackedUp: Boolean;
  DeviceIdBackupPath: String;
  DeviceIdBackedUp: Boolean;

// ── Task Scheduler: auto-start on login + auto-restart on crash ──

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
    '<?xml version="1.0">' + #13#10 +
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' + #13#10 +
    '  <RegistrationInfo>' + #13#10 +
    '    <Description>MavOps TimeTracker Agent - runs in background, auto-restarts on crash</Description>' + #13#10 +
    '  </RegistrationInfo>' + #13#10 +
    '  <Triggers>' + #13#10 +
    '    <LogonTrigger>' + #13#10 +
    '      <Enabled>true</Enabled>' + #13#10 +
    '    </LogonTrigger>' + #13#10 +
    '  </Triggers>' + #13#10 +
    '  <Principals>' + #13#10 +
    '    <Principal id="Author">' + #13#10 +
    '      <LogonType>InteractiveToken</LogonType>' + #13#10 +
    '      <RunLevel>LeastPrivilege</RunLevel>' + #13#10 +
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

procedure RemoveScheduledTask;
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/delete /tn "MavOps TimeTracker" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  DeleteFile(ExpandConstant('{userstartup}\TimeTracker Agent.lnk'));
end;


// ── Config backup: saves config.json and .device_id to temp before any cleanup ──

procedure BackupUserConfig();
var
  UserProfile: String;
  ConfigPath: String;
  DeviceIdPath: String;
  AppDataDeviceId: String;
begin
  UserProfile := GetEnv('USERPROFILE');
  ConfigBackupPath := ExpandConstant('{tmp}\timetracker_config_backup.json');
  DeviceIdBackupPath := ExpandConstant('{tmp}\timetracker_deviceid_backup.txt');
  ConfigBackedUp := False;
  DeviceIdBackedUp := False;

  // Backup config.json (contains api_key, server_device_id, api_base)
  ConfigPath := UserProfile + '\.timetracker\config.json';
  if FileExists(ConfigPath) then begin
    if FileCopy(ConfigPath, ConfigBackupPath, False) then begin
      ConfigBackedUp := True;
      Log('Backed up config.json to ' + ConfigBackupPath);
    end else
      Log('WARNING: Failed to backup config.json');
  end else
    Log('No config.json found at ' + ConfigPath);

  // Backup .device_id (check both locations)
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


// ── Config restore: puts config.json and .device_id back after install ──

procedure RestoreUserConfig();
var
  UserProfile: String;
  ConfigDir: String;
  ConfigPath: String;
  DeviceIdPath: String;
begin
  // Skip restore if user requested clean install
  if IsTaskSelected('cleaninstall') then begin
    Log('Clean install selected - skipping config restore');
    Exit;
  end;

  UserProfile := GetEnv('USERPROFILE');
  ConfigDir := UserProfile + '\.timetracker';
  ConfigPath := ConfigDir + '\config.json';
  DeviceIdPath := ConfigDir + '\.device_id';

  // Ensure directory exists
  if not DirExists(ConfigDir) then
    ForceDirectories(ConfigDir);

  // Restore config.json (only if missing - don't overwrite a fresh pair)
  if ConfigBackedUp then begin
    if not FileExists(ConfigPath) then begin
      if FileCopy(ConfigBackupPath, ConfigPath, False) then
        Log('Restored config.json from backup')
      else
        Log('WARNING: Failed to restore config.json');
    end else
      Log('config.json already exists - skipping restore');
  end;

  // Restore .device_id
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


// ── Existing cleanup procedures ──

procedure CleanupOldInstalls();
var
  ResultCode: Integer;
begin
  Exec('taskkill', '/F /IM TimeTracker.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill', '/F /IM TimeTrackerAgent.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
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

  // ALWAYS backup config BEFORE any cleanup
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
    Sleep(500);
  end;

  // ── After install: restore config, then create scheduled task ──
  if CurStep = ssPostInstall then begin
    RestoreUserConfig();
    CreateScheduledTask;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveScheduledTask;

    if MsgBox('Do you want to remove all TimeTracker settings and data?', mbConfirmation, MB_YESNO) = IDYES then
      CleanupUserData();
  end;
end;
