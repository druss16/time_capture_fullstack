@echo off
REM TimeTracker Windows Build Script
REM Run this from the windows_agent folder

echo ========================================
echo TimeTracker Windows Build
echo ========================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    pause
    exit /b 1
)

REM Install dependencies
echo [1/4] Installing dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Clean previous builds
echo.
echo [2/4] Cleaning previous builds...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist *.spec del /f *.spec

REM Build GUI (windowed, no console)
echo.
echo [3/4] Building TimeTracker.exe (GUI)...
python -m PyInstaller --onefile --windowed --name "TimeTracker" --icon "timetracker.ico" gui.py
if errorlevel 1 (
    echo ERROR: Failed to build TimeTracker.exe
    pause
    exit /b 1
)

REM Build Agent (no console, background service)
echo.
echo [4/4] Building TimeTrackerAgent.exe (Background Agent)...
python -m PyInstaller --onefile --noconsole --name "TimeTrackerAgent" --icon "timetracker.ico" --hidden-import=timetracker_gui --add-data "timetracker_gui.py;." main.py
if errorlevel 1 (
    echo ERROR: Failed to build TimeTrackerAgent.exe
    pause
    exit /b 1
)

REM Copy both exes to single dist folder
echo.
echo Finalizing...
copy dist\TimeTrackerAgent.exe dist\TimeTrackerAgent.exe >nul 2>&1

echo.
echo ========================================
echo BUILD COMPLETE!
echo ========================================
echo.
echo Output files in dist\ folder:
echo   - TimeTracker.exe      (Configuration GUI)
echo   - TimeTrackerAgent.exe (Background Agent)
echo.
echo Next steps:
echo   1. Install Inno Setup from https://jrsoftware.org/isinfo.php
echo   2. Open installer.iss in Inno Setup
echo   3. Click Build -^> Compile
echo   4. Find TimeTracker-Setup.exe in Output\ folder
echo.
pause
