@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title LAVRENTIY Installer
color 0C

set "INSTALL_DIR=%USERPROFILE%\Lavrentiy"
set "PROFILE_DIR=%USERPROFILE%\.lavrentiy"
set "TEMP_PY=%TEMP%\python-installer.exe"

echo.
echo  +===============================================+
echo  :     L A V R E N T I Y   S E T U P            :
echo  :     Voice Reconstruction Engine v1.0          :
echo  +===============================================+
echo.

:: ─── Check admin (warn but don't block) ───
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [*] Not running as admin. Python install may need elevation.
    echo      If it fails, right-click install.bat → Run as administrator.
    echo.
)

:: ─── [1/6] API Key ───
echo  [1/6] Setting OpenAI API key...
set "API_KEY="
if not exist "%~dp0api_key.txt" (
    echo  [!] api_key.txt not found next to installer.
    set /p API_KEY="  Paste OpenAI key now: "
) else (
    for /f "usebackq delims=" %%k in ("%~dp0api_key.txt") do set "API_KEY=%%k"
)
if not defined API_KEY (
    echo  [!] No API key provided.
    pause
    exit /b 1
)
setx OPENAI_API_KEY "%API_KEY%" >nul 2>&1
set "OPENAI_API_KEY=%API_KEY%"
echo  [OK] API key set.
echo.

:: ─── [2/6] Resolve Python ───
echo  [2/6] Resolving Python...
call :resolve_python
if not defined PYTHON_EXE (
    echo  [*] Python not found. Installing Python 3.12...
    call :install_python
    call :resolve_python
)
if not defined PYTHON_EXE (
    echo  [!] FATAL: Python installed but not found.
    echo      Try: close this window, open a NEW cmd, run install.bat again.
    pause
    exit /b 1
)
for %%F in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpF"
set "PYTHONW_EXE=%PYTHON_DIR%pythonw.exe"
if not exist "%PYTHONW_EXE%" (
    echo  [*] pythonw.exe not found — launcher will show console window.
    set "PYTHONW_EXE=%PYTHON_EXE%"
)
echo  [OK] Python:  %PYTHON_EXE%
echo  [OK] Pythonw: %PYTHONW_EXE%
echo.

:: ─── [3/6] Install packages ───
echo  [3/6] Installing Python packages...
"%PYTHON_EXE%" -m ensurepip --upgrade >nul 2>&1
"%PYTHON_EXE%" -m pip --disable-pip-version-check install --upgrade pip >nul 2>&1
"%PYTHON_EXE%" -m pip --disable-pip-version-check install openai sounddevice soundfile keyboard pyperclip pyautogui numpy scipy
if errorlevel 1 (
    echo  [!] Package installation failed.
    pause
    exit /b 1
)
echo  [OK] Packages installed.
echo.

:: ─── [4/6] Install app files ───
echo  [4/6] Installing app files...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if exist "%~dp0lavrentiy.py" (
    copy /Y "%~dp0lavrentiy.py" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0dashboard.html" "%INSTALL_DIR%\" >nul
    if exist "%~dp0lavrentiy.ico" copy /Y "%~dp0lavrentiy.ico" "%INSTALL_DIR%\" >nul
) else (
    echo  [*] Downloading from GitHub...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/lavrentiy.py' -OutFile '%INSTALL_DIR%\lavrentiy.py'"
    if errorlevel 1 goto :download_fail
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/dashboard.html' -OutFile '%INSTALL_DIR%\dashboard.html'"
    if errorlevel 1 goto :download_fail
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/gugosf114/lavrentiy/main/lavrentiy.ico' -OutFile '%INSTALL_DIR%\lavrentiy.ico'"
)
if not exist "%INSTALL_DIR%\lavrentiy.py" (
    echo  [!] lavrentiy.py missing after install.
    pause
    exit /b 1
)
:: Write launcher with absolute pythonw path
> "%INSTALL_DIR%\lavrentiy.bat" echo @echo off
>> "%INSTALL_DIR%\lavrentiy.bat" echo cd /d "%INSTALL_DIR%"
>> "%INSTALL_DIR%\lavrentiy.bat" echo start "" "%PYTHONW_EXE%" "%INSTALL_DIR%\lavrentiy.py"
if not exist "%INSTALL_DIR%\lavrentiy.bat" (
    echo  [!] Failed to create launcher.
    pause
    exit /b 1
)
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"
copy /Y "%INSTALL_DIR%\dashboard.html" "%PROFILE_DIR%\" >nul
echo  [OK] Files installed to %INSTALL_DIR%
echo.

:: ─── [5/6] Desktop shortcut (VBScript — OneDrive-safe) ───
echo  [5/6] Creating desktop shortcut...
set "ICO_PATH=%INSTALL_DIR%\lavrentiy.ico"

> "%TEMP%\lavrentiy_shortcut.vbs" (
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo sDesktop = oWS.SpecialFolders^("Desktop"^)
echo sLinkFile = sDesktop ^& "\Lavrentiy.lnk"
echo Set oLink = oWS.CreateShortcut^(sLinkFile^)
echo oLink.TargetPath = "%INSTALL_DIR%\lavrentiy.bat"
echo oLink.WorkingDirectory = "%INSTALL_DIR%"
echo oLink.Description = "Lavrentiy Voice Engine"
echo Set oFSO = CreateObject^("Scripting.FileSystemObject"^)
echo If oFSO.FileExists^("%ICO_PATH%"^) Then
echo     oLink.IconLocation = "%ICO_PATH%,0"
echo End If
echo oLink.Save
echo If oFSO.FileExists^(sLinkFile^) Then
echo     WScript.Echo "OK"
echo Else
echo     WScript.Echo "FAIL"
echo End If
)

set "SHORTCUT_OK="
for /f "usebackq delims=" %%r in (`cscript //nologo "%TEMP%\lavrentiy_shortcut.vbs" 2^>nul`) do set "SHORTCUT_OK=%%r"
del "%TEMP%\lavrentiy_shortcut.vbs" >nul 2>&1

if "%SHORTCUT_OK%"=="OK" (
    echo  [OK] Shortcut created on Desktop.
) else (
    echo  [!] Shortcut creation failed.
    echo      Launcher available at: %INSTALL_DIR%\lavrentiy.bat
)
echo.

:: ─── [6/6] Verify ───
echo  [6/6] Verifying...
if not exist "%PYTHONW_EXE%" (
    echo  [!] pythonw not found at expected path.
    pause
    exit /b 1
)
if not exist "%INSTALL_DIR%\lavrentiy.py" (
    echo  [!] App script missing.
    pause
    exit /b 1
)
echo.
echo  ==========================================
echo  DONE.
echo  Double-click Desktop shortcut: Lavrentiy
echo  Dashboard: http://localhost:7878
echo  ==========================================
echo.
echo  Hotkeys: F9=record  F10=tone  F11=layer
echo           F12=stats  F3x3=quit
echo.
pause
exit /b 0

:download_fail
echo  [!] Failed to download required files.
pause
exit /b 1

:install_python
echo  [*] Downloading Python 3.12 from python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.2/python-3.12.2-amd64.exe' -OutFile '%TEMP_PY%'"
if errorlevel 1 (
    echo  [!] Could not download Python installer.
    exit /b 1
)
echo  [*] Running installer (all-users)...
start /wait "" "%TEMP_PY%" /quiet InstallAllUsers=1 Include_pip=1 PrependPath=0
if errorlevel 1 (
    echo  [*] All-users failed, trying per-user...
    start /wait "" "%TEMP_PY%" /quiet InstallAllUsers=0 Include_pip=1 PrependPath=0
)
del "%TEMP_PY%" >nul 2>&1
exit /b 0

:resolve_python
set "PYTHON_EXE="

:: Probe 1: py launcher (fastest — covers any machine with Python in PATH)
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if exist "%%P" if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE exit /b 0

:: Probe 2: Native registry query (handles fresh installs, no PATH needed)
:: Check ExecutablePath first (exact), then (Default) with/without trailing \
for %%V in (3.12 3.13 3.14) do (
    for %%H in (
        "HKLM\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKCU\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore\%%V\InstallPath"
    ) do (
        if not defined PYTHON_EXE (
            for /f "tokens=2*" %%a in ('reg query %%H /v ExecutablePath 2^>nul') do (
                if exist "%%b" set "PYTHON_EXE=%%b"
            )
        )
        if not defined PYTHON_EXE (
            for /f "tokens=2*" %%a in ('reg query %%H /ve 2^>nul') do (
                if exist "%%bpython.exe" (
                    set "PYTHON_EXE=%%bpython.exe"
                ) else if exist "%%b\python.exe" (
                    set "PYTHON_EXE=%%b\python.exe"
                )
            )
        )
    )
)
if defined PYTHON_EXE exit /b 0

:: Probe 3: Hardcoded common paths (last resort)
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"
    "%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe"
    "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python314\python.exe"
) do (
    if exist %%d if not defined PYTHON_EXE set "PYTHON_EXE=%%~d"
)
exit /b 0
