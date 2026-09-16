@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  Nexino Print Agent - Inno Setup Builder
echo ============================================

set "ROOT=%~dp0"
set "ELECTRON_DIR=%ROOT%electron"
set "DIST_DIR=%ELECTRON_DIR%\dist-installer"
set "UNPACKED=%DIST_DIR%\win-unpacked"
set "BUILD_DIR=%DIST_DIR%\inno-build"
set "PYTHON_EMBED=%BUILD_DIR%\python"
set "AGENT_DIR=%BUILD_DIR%\agent\nexino_agent"
set "ISS_FILE=%ROOT%installer.iss"

REM Get version from package.json using PowerShell
for /f %%a in ('powershell -Command "(Get-Content '%ELECTRON_DIR%\package.json' | ConvertFrom-Json).version"') do set "VERSION=%%a"
echo Version: %VERSION%

REM Step 1: Clean and create build directory
echo.
echo [1/6] Preparing build directory...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"

REM Step 2: Copy Electron app
echo [2/6] Copying Electron app...
xcopy /s /e /q "%UNPACKED%\*" "%BUILD_DIR%\app\"

REM Step 3: Download Python embeddable package
echo [3/6] Downloading Python embeddable package...
set "PYTHON_VER=3.12.6"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VER%/python-%PYTHON_VER%-embed-amd64.zip"
set "PYTHON_ZIP=%BUILD_DIR%\python-embed.zip"

if not exist "%PYTHON_EMBED%" mkdir "%PYTHON_EMBED%"
curl -L -o "%PYTHON_ZIP%" "%PYTHON_URL%"
if errorlevel 1 (
    echo ERROR: Failed to download Python embeddable package
    exit /b 1
)

REM Extract Python
echo Extracting Python...
powershell -Command "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_EMBED%' -Force"
del "%PYTHON_ZIP%"

REM Step 4: Install pip into embedded Python
echo [4/6] Installing pip...
curl -L -o "%PYTHON_EMBED%\get-pip.py" "https://bootstrap.pypa.io/get-pip.py"
"%PYTHON_EMBED%\python.exe" "%PYTHON_EMBED%\get-pip.py" --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install pip
    exit /b 1
)
del "%PYTHON_EMBED%\get-pip.py"

REM Enable site-packages by uncommenting import site in python312._pth
echo Enabling site-packages...
powershell -Command "$files = Get-ChildItem '%PYTHON_EMBED%\*._pth'; foreach($f in $files) { $c = Get-Content $f.FullName -Raw; $c = $c -replace '#import site','import site'; Set-Content $f.FullName $c }"

REM Step 5: Install dependencies
echo [5/6] Installing Python dependencies...
"%PYTHON_EMBED%\python.exe" -m pip install -r "%ROOT%requirements.txt" --no-warn-script-location --quiet
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies
    exit /b 1
)

REM Copy agent code
echo Copying agent code...
mkdir "%BUILD_DIR%\agent"
mkdir "%AGENT_DIR%"
xcopy /s /e /q "%ROOT%nexino_agent\*" "%AGENT_DIR%\"
copy /y "%ROOT%.env" "%BUILD_DIR%\" 2>nul
copy /y "%ROOT%requirements.txt" "%BUILD_DIR%\"

REM Step 6: Build Inno Setup installer
echo [6/6] Building Inno Setup installer...
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo ERROR: Inno Setup not found
    echo Please install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    exit /b 1
)

"%ISCC%" /D"AppVersion=%VERSION%" "%ISS_FILE%"
if errorlevel 1 (
    echo ERROR: Inno Setup build failed
    exit /b 1
)

echo.
echo ============================================
echo  Build complete!
echo  Installer: %DIST_DIR%\NexinoPrintAgent-%VERSION%-Setup.exe
echo ============================================
pause
