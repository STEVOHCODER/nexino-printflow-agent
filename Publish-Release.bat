@echo off
title Nexino Print Agent - Publish Release
color 0B
cls

echo ============================================
echo    PUBLISH GITHUB RELEASE
echo ============================================
echo.
echo This script builds the app and publishes it
echo as a GitHub release for auto-updates.
echo.

cd /d "%~dp0"

echo [1/4] Checking GitHub CLI...
gh --version >nul 2>&1
if errorlevel 1 (
    echo GitHub CLI not found. Install from: https://cli.github.com/
    echo.
    echo Alternative: Use the publish command manually:
    echo   cd electron
    echo   npm run publish
    echo.
    pause
    exit /b 1
)
echo GitHub CLI found.
echo.

echo [2/4] Getting version from package.json...
cd electron
for /f "tokens=2 delims=:, " %%a in ('findstr "version" package.json') do (
    set VERSION=%%~a
)
set VERSION=%VERSION:"=%
echo Version: %VERSION%
echo.

echo [3/4] Building and publishing...
echo This will:
echo   - Build the Windows installer
echo   - Create a GitHub release
echo   - Upload the installer as a release asset
echo.
echo Make sure you are logged into GitHub CLI: gh auth login
echo.
pause

call npm run publish
echo.

echo [4/4] Done!
echo.
echo Release published to:
echo https://github.com/STEVOHCODER/nexino-printflow-agent/releases/tag/v%VERSION%
echo.
echo Users can now update from within the app.
echo.
pause
