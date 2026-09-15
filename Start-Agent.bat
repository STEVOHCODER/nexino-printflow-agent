@echo off
title Nexino Print Agent
color 0B
cls

echo ============================================
echo    NEXINO PRINT AGENT - STARTER
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python 3.10+
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

echo [2/3] Installing dependencies...
pip install -r requirements.txt -q 2>nul
pip install -e . -q 2>nul
echo Done.
echo.

echo [3/3] Starting agent...
echo Backend: https://backend-mauve-delta-32.vercel.app
echo Agent ID: AGENT-001
echo.
echo ============================================
echo    Press Ctrl+C to stop
echo ============================================
echo.

python -m nexino_agent start --agent-id AGENT-001 --backend-url https://backend-mauve-delta-32.vercel.app
