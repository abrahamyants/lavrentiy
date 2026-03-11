@echo off
:: ═══════════════════════════════════════════════════════
::  LAVRENTIY — One-Click Installer
::  "We've got a file on you"
::
::  Run this as Administrator on any Windows 10/11 machine.
::  It installs Python (if missing), dependencies, sets the
::  API key, and creates a desktop shortcut.
::
::  BEFORE RUNNING: Create a file called "api_key.txt" in
::  the same folder as this script containing ONLY your
::  OpenAI API key (starts with sk-proj-...).
:: ═══════════════════════════════════════════════════════
title LAVRENTIY Installer
color 0C
echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║         L A V R E N T I Y   S E T U P        ║
echo  ║       Voice Reconstruction Engine v1.0        ║
echo  ╚═══════════════════════════════════════════════╝
echo.

:: ─── Check admin ───
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] This installer needs Administrator privileges.
    echo      Right-click install.bat ^> "Run as administrator"
    echo.
    pause
    exit /b 1
)

:: ─── Read API Key from file ───
echo  [1/5] Setting OpenAI API key...
if exist "%~dp0api_key.txt" (
    set /p API_KEY=<"%~dp0api_key.txt"
) else (
    echo  [!] api_key.txt not found!
    echo      Create a file called "api_key.txt" next to this script
    echo      containing your OpenAI API key (sk-proj-...).
    echo.
    set /p API_KEY="  Or paste your key here: "
)
if "%API_KEY%"=="" (
    echo  [!] No API key provided. Cannot continue.
    pause
    exit /b 1
)
setx OPENAI_API_KEY "%API_KEY%" >nul 2>&1
set "OPENAI_API_KEY=%API_KEY%"
echo  [OK] API key set.
echo.

:: ─── Check Python ───
echo  [2/5] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Python not found. Installing Python 3.12...
    echo      Downloading from python.org...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.2/python-3.12.2-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
    echo      Running installer (this takes a minute)...
    "%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
    echo  [OK] Python installed. You may need to restart this script.
    echo.
    set "PATH=%PATH%;C:\Program Files\Python312;C:\Program Files\Python312\Scripts"
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v found.
)
echo.

:: ─── Install dependencies ───
echo  [3/5] Installing Python packages...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install openai sounddevice soundfile keyboard pyperclip pyautogui numpy scipy
echo.
echo  [OK] All packages installed.
echo.

:: ─── Set install directory ───
echo  [4/5] Setting up Lavrentiy...
set "INSTALL_DIR=%USERPROFILE%\Lavrentiy"

if exist "%~dp0lavrentiy.py" (
    echo  [*] Copying from current directory...
    if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
    copy /Y "%~dp0lavrentiy.py" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0dashboard.html" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0lavrentiy.bat" "%INSTALL_DIR%\" >nul
) else (
    echo  [*] Cloning from GitHub...
    git clone https://github.com/gugosf114/lavrentiy.git "%INSTALL_DIR%" 2>nul
    if %errorlevel% neq 0 (
        echo  [!] Git not found. Downloading files directly...
        if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
        powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/lavrentiy.py' -OutFile '%INSTALL_DIR%\lavrentiy.py'"
        powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/dashboard.html' -OutFile '%INSTALL_DIR%\dashboard.html'"
        powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/lavrentiy.bat' -OutFile '%INSTALL_DIR%\lavrentiy.bat'"
    )
)
echo  [OK] Files installed to %INSTALL_DIR%
echo.

:: ─── Create Desktop shortcut ───
echo  [5/5] Creating desktop shortcut...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\Lavrentiy.lnk'); $s.TargetPath = '%INSTALL_DIR%\lavrentiy.bat'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'Lavrentiy Voice Engine'; $s.Save()"
echo  [OK] "Lavrentiy" shortcut on Desktop.
echo.

:: ─── Done ───
echo  ═══════════════════════════════════════════════
echo   DONE! Double-click "Lavrentiy" on the Desktop.
echo   Dashboard opens at http://localhost:7878
echo.
echo   Hotkeys:
echo     F9 (hold) = Record
echo     F10       = Cycle tone
echo     F11       = Cycle layer
echo     F3 x3     = Quit
echo  ═══════════════════════════════════════════════
echo.
pause
