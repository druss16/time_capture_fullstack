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
Name: "startupicon"; Description: "Start TimeTracker Agent when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked
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
Name: "{userstartup}\TimeTracker Agent"; Filename: "{app}\TimeTrackerAgent.exe"; Parameters: "start"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\TimeTrackerAgent.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopAgent"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{userappdata}\TimeTracker"
Type: filesandordirs; Name: "{localappdata}\Programs\TimeTracker"

[Code]
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
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('Do you want to remove all TimeTracker settings and data?', mbConfirmation, MB_YESNO) = IDYES then
      CleanupUserData();
  end;
end;