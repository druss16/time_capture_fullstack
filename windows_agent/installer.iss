; TimeTracker Windows Installer Script
; Inno Setup 6.x
; Download Inno Setup from: https://jrsoftware.org/isinfo.php
#define MyAppName "TimeTracker"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "MavOps"
#define MyAppURL "https://github.com/druss16/timetracker-releases"
#define MyAppExeName "TimeTracker.exe"

[Setup]
; NOTE: AppId uniquely identifies this app. Do not use the same AppId in other installers.
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
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
; Privileges - install for current user by default
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Close running applications
CloseApplications=force
CloseApplicationsFilter=*.exe
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start TimeTracker Agent when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Main GUI application
Source: "dist\TimeTracker.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace uninsrestartdelete
; Background agent
Source: "dist\TimeTrackerAgent.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace uninsrestartdelete
; Icon file (for uninstaller and shortcuts)
Source: "timetracker.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\timetracker.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
; Desktop icon (optional)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\timetracker.ico"; Tasks: desktopicon
; Startup folder (optional - starts agent on login)
Name: "{userstartup}\TimeTracker Agent"; Filename: "{app}\TimeTrackerAgent.exe"; Parameters: "start"; Tasks: startupicon

[Run]
; Option to launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop agent before uninstall
Filename: "{app}\TimeTrackerAgent.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopAgent"

[UninstallDelete]
; Clean up config and data on uninstall (optional - uncomment if desired)
; Type: filesandordirs; Name: "{userappdata}\TimeTracker"
; Type: filesandordirs; Name: "{userpf}\.timetracker"

[Code]
// Kill TimeTracker processes before install
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    // Kill any running TimeTracker processes
    Exec('taskkill', '/F /IM TimeTracker.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill', '/F /IM TimeTrackerAgent.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    // Small delay to let processes fully terminate
    Sleep(500);
  end;
end;

// Also kill on initialize in case upgrade is happening
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill', '/F /IM TimeTracker.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill', '/F /IM TimeTrackerAgent.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Result := True;
end;