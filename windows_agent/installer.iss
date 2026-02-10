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
Type: filesandordirs; Name: "{userappdata}\TimeTracker"
Type: filesandordirs; Name: "{localappdata}\Programs\TimeTracker"

[Code]

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

  // XML task definition gives us restart-on-failure (schtasks /create can't do that)
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

  // Write XML to temp file
  SaveStringToFile(XmlPath, XmlContent, False);

  // Delete old task if exists
  Exec('schtasks.exe', '/delete /tn "MavOps TimeTracker" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // Create task from XML (supports RestartOnFailure)
  Exec('schtasks.exe',
       '/create /tn "MavOps TimeTracker" /xml "' + XmlPath + '" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if ResultCode = 0 then
    Log('Scheduled task created successfully')
  else
    Log('Scheduled task creation failed with code: ' + IntToStr(ResultCode));

  // Clean up temp XML
  DeleteFile(XmlPath);

  // Also remove old startup shortcut if it exists (from previous versions)
  DeleteFile(ExpandConstant('{userstartup}\TimeTracker Agent.lnk'));
end;

procedure RemoveScheduledTask;
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/delete /tn "MavOps TimeTracker" /f',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Also clean up any old startup shortcut
  DeleteFile(ExpandConstant('{userstartup}\TimeTracker Agent.lnk'));
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

  // ── Create scheduled task after install completes ──
  if CurStep = ssPostInstall then
    CreateScheduledTask;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Remove the scheduled task
    RemoveScheduledTask;

    if MsgBox('Do you want to remove all TimeTracker settings and data?', mbConfirmation, MB_YESNO) = IDYES then
      CleanupUserData();
  end;
end;