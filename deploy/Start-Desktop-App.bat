@echo off
title Nexino Print Agent - Desktop App
color 0B
cls

echo ============================================
echo    NEXINO PRINT AGENT - DESKTOP APP
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found! Please install Node.js 18+
    echo Download from: https://nodejs.org/
    pause
    exit /b 1
)
echo Node.js is available.
echo.

echo [2/2] Starting desktop app...
echo.

cd electron
npm start
