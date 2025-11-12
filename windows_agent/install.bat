@echo off
REM TimeTracker Windows Agent Installer
REM This script installs all dependencies and sets up the agent

echo ========================================
echo TimeTracker Windows Agent Installer
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo.
    echo Please install Python from https://python.org
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

echo [1/4] Python found!
python --version
echo.

REM Check if pip is available
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip is not available
    echo.
    pause
    exit /b 1
)

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    echo.
    pause
    exit /b 1
)

echo.
echo [3/4] Installing pywin32 post-install scripts...
python Scripts\pywin32_postinstall.py -install

echo.
echo [4/4] Creating config directory...
if not exist "%USERPROFILE%\.timetracker" mkdir "%USERPROFILE%\.timetracker"

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo Next steps:
echo   1. Run: python gui.py
echo   2. Enter your configuration
echo   3. Click "Start Agent"
echo.
echo Or run directly: python main.py start
echo.
pause