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
; Force clean install directory before copying files
Type: filesandordirs; Name: "{app}"

[Files]
; Main GUI application (folder from onedir build)
Source: "dist\TimeTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Background agent (folder from onedir build)
Source: "dist\TimeTrackerAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Icon file
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
Type: filesandordirs; Name: "{userpf}\TimeTracker"
Type: filesandordirs; Name: "{localappdata}\Programs\TimeTracker"

[Code]
procedure CleanupOldInstalls();
var
  ResultCode: Integer;
  Paths: array of String;
  I: Integer;
begin
  // Kill any running TimeTracker processes
  Exec('taskkill', '/F /IM TimeTracker.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill', '/F /IM TimeTrackerAgent.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
  
  // List of all possible old install locations
  SetArrayLength(Paths, 4);
  Paths[0] := ExpandConstant('{localappdata}\TimeTracker');
  Paths[1] := ExpandConstant('{localappdata}\Programs\TimeTracker');
  Paths[2] := ExpandConstant('{userpf}\TimeTracker');
  Paths[3] := ExpandConstant('{commonpf}\TimeTracker');
  
  for I := 0 to GetArrayLength(Paths) - 1 do
  begin
    if DirExists(Paths[I]) then
    begin
      Log('Removing old install: ' + Paths[I]);
      DelTree(Paths[I], True, True, True);
    end;
  end;
end;

procedure CleanupUserData();
var
  UserProfile: String;
  AppData: String;
begin
  UserProfile := GetEnv('USERPROFILE');
  AppData := ExpandConstant('{userappdata}');
  
  // Clear config directory (~/.timetracker)
  if DirExists(UserProfile + '\.timetracker') then
  begin
    Log('Clearing user config: ' + UserProfile + '\.timetracker');
    DelTree(UserProfile + '\.timetracker', True, True, True);
  end;
  
  // Clear app data (%APPDATA%/TimeTracker)
  if DirExists(AppData + '\TimeTracker') then
  begin
    Log('Clearing app data: ' + AppData + '\TimeTracker');
    DelTree(AppData + '\TimeTracker', True, True, True);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  
  // Always clean up old installations
  CleanupOldInstalls();
  
  // If "Fresh install" is checked, also clear user data
  if IsTaskSelected('cleaninstall') then
  begin
    Log('Fresh install selected - clearing user data');
    CleanupUserData();
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    // One more kill attempt right before install
    Exec('taskkill', '/F /IM TimeTracker.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill', '/F /IM TimeTrackerAgent.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Ask user if they want to remove settings
    if MsgBox('Do you want to remove all TimeTracker settings and data?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      CleanupUserData();
    end;
  end;
end;