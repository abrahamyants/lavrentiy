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

:: Fix working directory when launched via "Run as administrator"
cd /d "%~dp0"

title LAVRENTIY Installer
color 0C
echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║         L A V R E N T I Y   S E T U P        ║
echo  ║       Voice Reconstruction Engine v1.0        ║
echo  ╚═══════════════════════════════════════════════╝
echo.

:: ─── Check admin (warn but don't block) ───
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [*] Note: Not running as admin. Python install may need admin.
    echo      If Python install fails, re-run as administrator.
    echo.
)

:: ─── Read API Key from file ───
echo  [1/5] Setting OpenAI API key...
set "API_KEY="
if not exist "%~dp0api_key.txt" goto :no_key_file
for /f "usebackq delims=" %%k in ("%~dp0api_key.txt") do set "API_KEY=%%k"
goto :key_done
:no_key_file
echo  [!] api_key.txt not found!
echo      Create a file called "api_key.txt" next to this script
echo      containing your OpenAI API key (sk-proj-...).
echo.
set /p API_KEY="  Or paste your key here: "
:key_done
if not defined API_KEY (
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
set "PYTHON_EXE="
:: Try PATH first
where python >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%p in ('where python 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%p"
    )
)
:: Search common install locations if not in PATH
if not defined PYTHON_EXE (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python314\python.exe"
        "%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"
        "%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe"
        "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
    ) do (
        if exist %%d if not defined PYTHON_EXE set "PYTHON_EXE=%%~d"
    )
)
if defined PYTHON_EXE goto :python_found
:: Not found anywhere — install it
echo  [!] Python not found. Installing Python 3.12...
echo      Downloading from python.org...
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.2/python-3.12.2-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
echo      Running installer (this takes a minute)...
"%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
echo  [OK] Python installed. Locating...
:: Find what was just installed
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "C:\Program Files\Python312\python.exe"
) do (
    if exist %%d if not defined PYTHON_EXE set "PYTHON_EXE=%%~d"
)
if not defined PYTHON_EXE (
    echo  [!] FATAL: Python installed but cannot be found.
    echo      Close this window, open a NEW command prompt, and run install.bat again.
    pause
    exit /b 1
)
:python_found
for %%F in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpF"
set "PYTHONW_EXE=%PYTHON_DIR%pythonw.exe"
echo  [OK] Found: %PYTHON_EXE%
echo.

:: ─── Install dependencies ───
echo  [3/5] Installing Python packages...
"%PYTHON_EXE%" -m pip install --upgrade pip >nul 2>&1
"%PYTHON_EXE%" -m pip install openai sounddevice soundfile keyboard pyperclip pyautogui numpy scipy
echo.
echo  [OK] All packages installed.
echo.

:: ─── Set install directory ───
echo  [4/5] Setting up Lavrentiy...
set "INSTALL_DIR=%USERPROFILE%\Lavrentiy"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

if exist "%~dp0lavrentiy.py" goto :copy_local
goto :clone_remote
:copy_local
echo  [*] Copying from current directory...
copy /Y "%~dp0lavrentiy.py" "%INSTALL_DIR%\" >nul
copy /Y "%~dp0dashboard.html" "%INSTALL_DIR%\" >nul
:: Write a launcher that uses the exact Python path we found
echo @echo off > "%INSTALL_DIR%\lavrentiy.bat"
echo start "" "%PYTHONW_EXE%" "%%~dp0lavrentiy.py" >> "%INSTALL_DIR%\lavrentiy.bat"
goto :files_done
:clone_remote
echo  [*] Downloading files from GitHub...
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/lavrentiy.py' -OutFile '%INSTALL_DIR%\lavrentiy.py'"
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/dashboard.html' -OutFile '%INSTALL_DIR%\dashboard.html'"
:: Write a launcher that uses the exact Python path we found
echo @echo off > "%INSTALL_DIR%\lavrentiy.bat"
echo start "" "%PYTHONW_EXE%" "%%~dp0lavrentiy.py" >> "%INSTALL_DIR%\lavrentiy.bat"
:files_done
echo  [OK] Files installed to %INSTALL_DIR%
echo.

:: ─── Set up profile directory + dashboard ───
echo  [5/6] Setting up profile directory...
set "PROFILE_DIR=%USERPROFILE%\.lavrentiy"
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"
copy /Y "%INSTALL_DIR%\dashboard.html" "%PROFILE_DIR%\" >nul
echo  [OK] Dashboard copied to %PROFILE_DIR%
echo.

:: ─── Create Desktop shortcut ───
echo  [6/6] Creating desktop shortcut...
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
