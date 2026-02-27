@echo off
REM ═══════════════════════════════════════════════════════
REM  TimeTracker MSI Build Script
REM  
REM  Prerequisites:
REM    - WiX Toolset v4: dotnet tool install -g wix
REM    - PyInstaller output in ..\dist\TimeTracker\ and ..\dist\TimeTrackerAgent\
REM
REM  Usage:
REM    build_msi.bat                            (build without embedded token)
REM    build_msi.bat ODT-XKCD-9F3A             (build with embedded token)
REM    build_msi.bat ODT-XKCD-9F3A 1.2.0       (build with token + version)
REM ═══════════════════════════════════════════════════════

set ORG_TOKEN=%1
set VERSION=%2
if "%VERSION%"=="" set VERSION=1.0.0

echo.
echo ╔═══════════════════════════════════════╗
echo ║  TimeTracker MSI Builder              ║
echo ║  Version: %VERSION%                   
echo ╚═══════════════════════════════════════╝
echo.

REM Step 1: Verify PyInstaller output exists
if not exist "..\dist\TimeTrackerAgent\TimeTrackerAgent.exe" (
    echo ERROR: PyInstaller output not found at ..\dist\TimeTrackerAgent\
    echo Run PyInstaller first, then re-run this script.
    exit /b 1
)

REM Step 2: Generate file list for WiX (heat.exe equivalent)
echo [1/4] Scanning files...
wix heat dir "..\dist\TimeTrackerAgent" -cg AgentFiles -dr INSTALLFOLDER -var var.AgentSource -ag -sfrag -srd -o AgentFiles.wxs
wix heat dir "..\dist\TimeTracker" -cg GUIFiles -dr INSTALLFOLDER -var var.GUISource -ag -sfrag -srd -o GUIFiles.wxs

REM Step 3: Build MSI
echo [2/4] Compiling...
if "%ORG_TOKEN%"=="" (
    echo Building WITHOUT embedded org token
    wix build TimeTracker.wxs AgentFiles.wxs GUIFiles.wxs ^
        -d AgentSource="..\dist\TimeTrackerAgent" ^
        -d GUISource="..\dist\TimeTracker" ^
        -o "TimeTracker-%VERSION%.msi"
) else (
    echo Building WITH org token: %ORG_TOKEN%
    wix build TimeTracker.wxs AgentFiles.wxs GUIFiles.wxs ^
        -d AgentSource="..\dist\TimeTrackerAgent" ^
        -d GUISource="..\dist\TimeTracker" ^
        -d OrgToken=%ORG_TOKEN% ^
        -o "TimeTracker-%VERSION%.msi"
)

if errorlevel 1 (
    echo.
    echo ❌ MSI build failed!
    exit /b 1
)

echo [3/4] MSI built successfully!

REM Step 4: Wrap for Intune (.intunewin)
echo [4/4] Creating Intune package...
if exist "IntuneWinAppUtil.exe" (
    IntuneWinAppUtil.exe -c "." -s "TimeTracker-%VERSION%.msi" -o "." -q
    echo ✅ Intune package created: TimeTracker-%VERSION%.intunewin
) else (
    echo ⚠  IntuneWinAppUtil.exe not found — skipping .intunewin creation
    echo    Download from: https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool
)

echo.
echo ═══════════════════════════════════════
echo  Output files:
echo    MSI:      TimeTracker-%VERSION%.msi
if exist "TimeTracker-%VERSION%.intunewin" echo    Intune:   TimeTracker-%VERSION%.intunewin
echo.
echo  Intune install command:
if "%ORG_TOKEN%"=="" (
    echo    msiexec /i TimeTracker-%VERSION%.msi /quiet ORG_TOKEN=YOUR-TOKEN-HERE
) else (
    echo    msiexec /i TimeTracker-%VERSION%.msi /quiet
    echo    (org token already embedded)
)
echo  Intune uninstall command:
echo    msiexec /x {PRODUCT-GUID} /quiet
echo  Detection rule:
echo    File exists: C:\Program Files\TimeTracker\TimeTrackerAgent.exe
echo ═══════════════════════════════════════