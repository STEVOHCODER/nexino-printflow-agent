@echo off
title Nexino Print Agent - Setup
color 0B
cls

echo ============================================
echo    NEXINO PRINT AGENT - SETUP
echo ============================================
echo.
echo This script will install and configure the
echo Nexino PrintFlow Agent on this machine.
echo.

cd /d "%~dp0"

REM Check Python
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.10+ from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo Found: %PYVER%
echo.

REM Check pip
echo [2/5] Checking pip...
pip --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip not found! Installing...
    python -m ensurepip --default-pip
)
echo pip is available.
echo.

REM Install dependencies
echo [3/5] Installing Python dependencies...
pip install -r requirements.txt -q
pip install -e . -q 2>nul
if errorlevel 1 (
    echo WARNING: Some dependencies may not have installed correctly.
    echo Trying alternative install...
    pip install requests python-dotenv psutil pywin32 Pillow -q
)
echo Dependencies installed.
echo.

REM Test import
echo [4/5] Testing agent import...
python -c "from nexino_agent import __version__; print(f'Agent version: {__version__}')" 2>nul
if errorlevel 1 (
    echo WARNING: Agent module not importable. Trying editable install...
    pip install -e . -q
)
echo.

REM Create .env if not exists
echo [5/5] Checking configuration...
if not exist ".env" (
    echo Creating default .env configuration...
    (
        echo NEXINO_BACKEND_URL=https://backend-mauve-delta-32.vercel.app
        echo AGENT_ID=AGENT-001
        echo AGENT_SECRET=nexino-printflow-agent-secret-2026
        echo STATION_ID=
        echo POLL_INTERVAL_SECONDS=3
        echo PRINTER_NAME=
        echo VIRTUAL_MODE=false
        echo LOG_LEVEL=INFO
        echo OUTPUT_DIRECTORY=
    ) > .env
    echo Default .env created.
) else (
    echo .env already exists.
)
echo.

echo ============================================
echo    SETUP COMPLETE
echo ============================================
echo.
echo Next steps:
echo   1. Run "Start-CLI-Agent.bat" to start the agent in CLI mode
echo   2. Run "Start-Desktop-App.bat" to open the desktop GUI
echo   3. Or run "python -m nexino_agent start" directly
echo.
echo Backend URL: https://backend-mauve-delta-32.vercel.app
echo.
pause
