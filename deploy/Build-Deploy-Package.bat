@echo off
title Nexino Print Agent - Build Deployment Package
color 0B
cls

echo ============================================
echo    BUILDING DEPLOYMENT PACKAGE
echo ============================================
echo.

cd /d "%~dp0"

set PKG_DIR=nexino-printflow-agent
set OUTPUT_DIR=dist-deploy

REM Clean previous build
if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"
mkdir "%OUTPUT_DIR%"

echo [1/5] Creating package structure...
mkdir "%OUTPUT_DIR%\%PKG_DIR%"
mkdir "%OUTPUT_DIR%\%PKG_DIR%\nexino_agent"
mkdir "%OUTPUT_DIR%\%PKG_DIR%\electron"
mkdir "%OUTPUT_DIR%\%PKG_DIR%\deploy"

echo [2/5] Copying agent code...
xcopy /s /e /q /y "nexino_agent\*" "%OUTPUT_DIR%\%PKG_DIR%\nexino_agent\"
copy /y "requirements.txt" "%OUTPUT_DIR%\%PKG_DIR%\"
copy /y "setup.py" "%OUTPUT_DIR%\%PKG_DIR%\"
copy /y ".env" "%OUTPUT_DIR%\%PKG_DIR%\" 2>nul
copy /y ".env.example" "%OUTPUT_DIR%\%PKG_DIR%\" 2>nul

echo [3/5] Copying Electron app...
copy /y "electron\main.js" "%OUTPUT_DIR%\%PKG_DIR%\electron\"
copy /y "electron\preload.js" "%OUTPUT_DIR%\%PKG_DIR%\electron\"
copy /y "electron\index.html" "%OUTPUT_DIR%\%PKG_DIR%\electron\"
copy /y "electron\package.json" "%OUTPUT_DIR%\%PKG_DIR%\electron\"
copy /y "electron\icon.*" "%OUTPUT_DIR%\%PKG_DIR%\electron\" 2>nul

echo [4/5] Copying setup scripts...
copy /y "deploy\*.bat" "%OUTPUT_DIR%\%PKG_DIR%\deploy\"
copy /y "Build-Installer.bat" "%OUTPUT_DIR%\%PKG_DIR%\"
copy /y "Start-Agent.bat" "%OUTPUT_DIR%\%PKG_DIR%\"
copy /y "Start-CLI-Agent.bat" "%OUTPUT_DIR%\%PKG_DIR%\" 2>nul
copy /y "Start-Desktop-App.bat" "%OUTPUT_DIR%\%PKG_DIR%\" 2>nul

echo [5/5] Creating README...
(
echo Nexino PrintFlow Agent - Deployment Package
echo ============================================
echo.
echo Requirements:
echo   - Python 3.10+ (https://www.python.org/downloads/)
echo   - Node.js 18+ (https://nodejs.org/) - only for desktop app
echo.
echo Quick Start:
echo   1. Extract this folder to the target machine
echo   2. Run "deploy\Setup-Agent.bat" to install dependencies
echo   3. Run "deploy\Start-CLI-Agent.bat" to start the agent
echo.
echo Desktop App:
echo   1. Run "Build-Installer.bat" to create the desktop installer
echo   2. Or run "deploy\Start-Desktop-App.bat" directly
echo.
echo Backend URL: https://backend-mauve-delta-32.vercel.app
echo Agent Secret: nexino-printflow-agent-secret-2026
echo.
) > "%OUTPUT_DIR%\%PKG_DIR%\README.txt"

echo.
echo ============================================
echo    PACKAGE CREATED SUCCESSFULLY
echo ============================================
echo.
echo Location: %OUTPUT_DIR%\%PKG_DIR%
echo.
echo To deploy:
echo   1. Copy the "%OUTPUT_DIR%\%PKG_DIR%" folder to the target machine
echo   2. Run "deploy\Setup-Agent.bat" on the target machine
echo   3. Run "deploy\Start-CLI-Agent.bat" or "deploy\Start-Desktop-App.bat"
echo.

REM Create zip if powershell is available
where powershell >nul 2>&1
if not errorlevel 1 (
    echo Creating ZIP archive...
    powershell -command "Compress-Archive -Path '%OUTPUT_DIR%\%PKG_DIR%' -DestinationPath '%OUTPUT_DIR%\nexino-printflow-agent.zip' -Force"
    echo ZIP created: %OUTPUT_DIR%\nexino-printflow-agent.zip
)

echo.
pause
