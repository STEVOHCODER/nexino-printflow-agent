@echo off
title Nexino Print Agent - Build Installer
color 0B
cls

echo ============================================
echo    BUILDING DESKTOP INSTALLER
echo ============================================
echo.

cd /d "%~dp0"

echo [1/5] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found! Please install Node.js 18+
    echo Download from: https://nodejs.org/
    pause
    exit /b 1
)
node --version
echo.

echo [2/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: Python not found. Installer will not bundle Python agent.
    echo The target machine will need Python installed separately.
    echo.
)
echo.

echo [3/5] Installing Electron dependencies...
cd electron
call npm install
echo.

echo [4/5] Building Windows installer...
call npm run build:win
echo.

echo [5/5] Building deployment package...
cd ..
call deploy\Build-Deploy-Package.bat
echo.

echo ============================================
echo    BUILD COMPLETE
echo ============================================
echo.
echo Desktop Installer:
echo   electron\dist-installer\Nexino Print Agent Setup *.exe
echo.
echo Deployment Package:
echo   deploy\dist-deploy\nexino-printflow-agent.zip
echo.
echo The deployment package includes:
echo   - Python agent code (nexino_agent/)
echo   - Electron app files
echo   - Setup and launcher scripts
echo   - Requirements file
echo.
pause
