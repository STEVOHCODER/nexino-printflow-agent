@echo off
title Nexino Print Agent - CLI Mode
color 0B
cls

echo ============================================
echo    NEXINO PRINT AGENT - CLI MODE
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Run Setup-Agent.bat first.
    pause
    exit /b 1
)
echo Python is available.
echo.

echo [2/2] Starting agent...
echo Backend: https://backend-mauve-delta-32.vercel.app
echo Mode: CLI
echo.
echo ============================================
echo    Press Ctrl+C to stop
echo ============================================
echo.

python -m nexino_agent start --agent-id AGENT-001 --backend-url https://backend-mauve-delta-32.vercel.app --virtual
