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

REM Get version from version.py
for /f "tokens=*" %%i in ('python -c "from version import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%i
if "%VERSION%"=="" (
    echo ERROR: Could not read version from version.py
    pause
    exit /b 1
)
echo Version: %VERSION%
echo.

REM Install dependencies
echo [1/5] Installing dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Clean previous builds
echo.
echo [2/5] Cleaning previous builds...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist *.spec del /f *.spec

REM Build GUI (windowed, no console)
echo.
echo [3/5] Building TimeTracker.exe (GUI)...
python -m PyInstaller --onefile --windowed --name "TimeTracker" --icon "timetracker.ico" gui.py
if errorlevel 1 (
    echo ERROR: Failed to build TimeTracker.exe
    pause
    exit /b 1
)

REM Build Agent (no console, background service)
echo.
echo [4/5] Building TimeTrackerAgent.exe (Background Agent)...
python -m PyInstaller --onefile --noconsole --name "TimeTrackerAgent" --icon "timetracker.ico" --hidden-import=timetracker_gui --add-data "timetracker_gui.py;." main.py
if errorlevel 1 (
    echo ERROR: Failed to build TimeTrackerAgent.exe
    pause
    exit /b 1
)

REM Build Watchdog (no console, background service)
echo.
echo [5/5] Building tt_watchdog.exe (External Watchdog)...
python -m PyInstaller --onefile --noconsole --name "tt_watchdog" tt_watchdog.py
if errorlevel 1 (
    echo ERROR: Failed to build tt_watchdog.exe
    pause
    exit /b 1
)

REM Verify all exes exist before zipping
if not exist dist\TimeTrackerAgent.exe (
    echo ERROR: TimeTrackerAgent.exe not found in dist\
    pause
    exit /b 1
)
if not exist dist\tt_watchdog.exe (
    echo ERROR: tt_watchdog.exe not found in dist\
    pause
    exit /b 1
)

REM Package into version-named zip for auto-update
REM IMPORTANT: zip name must match what backend returns in zip_url
REM backend returns: TimeTrackerAgent-{version}.zip
echo.
echo Packaging update zip as TimeTrackerAgent-%VERSION%.zip...
powershell -Command "Compress-Archive -Path 'dist\TimeTrackerAgent.exe','dist\tt_watchdog.exe' -DestinationPath 'dist\TimeTrackerAgent-%VERSION%.zip' -Force"
if errorlevel 1 (
    echo ERROR: Failed to create zip
    pause
    exit /b 1
)
echo Created dist\TimeTrackerAgent-%VERSION%.zip

REM Verify zip was created and has reasonable size
for %%A in (dist\TimeTrackerAgent-%VERSION%.zip) do set ZIPSIZE=%%~zA
if %ZIPSIZE% LSS 10485760 (
    echo ERROR: Zip too small (%ZIPSIZE% bytes) - something went wrong
    pause
    exit /b 1
)
echo Zip size: %ZIPSIZE% bytes - OK

echo.
echo ========================================
echo BUILD COMPLETE!
echo ========================================
echo.
echo Output files in dist\ folder:
echo   - TimeTracker.exe                    (Configuration GUI)
echo   - TimeTrackerAgent.exe               (Background Agent)
echo   - tt_watchdog.exe                    (External Watchdog)
echo   - TimeTrackerAgent-%VERSION%.zip     (Auto-update package)
echo.
echo !! THIS ZIP IS FOR LOCAL TESTING ONLY !!
echo For production release:
echo   git tag v%VERSION%
echo   git push origin v%VERSION%
echo GitHub Action builds signed exes and publishes to releases.
echo Agents auto-update within 5 minutes of tag push.
echo.
pause