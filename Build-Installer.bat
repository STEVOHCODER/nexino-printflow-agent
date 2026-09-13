@echo off
title Nexino Print Agent - Build Installer
color 0B
cls

echo ============================================
echo    BUILDING DESKTOP INSTALLER
echo ============================================
echo.

cd /d "%~dp0"

echo [1/4] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found! Please install Node.js 18+
    echo Download from: https://nodejs.org/
    pause
    exit /b 1
)
node --version
echo.

echo [2/4] Installing Electron dependencies...
cd electron
call npm install
echo.

echo [3/4] Building Windows installer...
call npm run build:win
echo.

echo [4/4] Done!
echo.
echo Installer created in: electron\dist-installer\
echo Look for "Nexino Print Agent Setup *.exe"
echo.
pause
