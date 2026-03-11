@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title LAVRENTIY Installer
color 0C

set "INSTALL_DIR=%USERPROFILE%\Lavrentiy"
set "PROFILE_DIR=%USERPROFILE%\.lavrentiy"
set "TEMP_PY=%TEMP%\python-installer.exe"

echo.
echo  [1/6] Setting OpenAI API key...
set "API_KEY="
if exist "%~dp0api_key.txt" (
    for /f "usebackq delims=" %%k in ("%~dp0api_key.txt") do set "API_KEY=%%k"
) else (
    echo  [!] api_key.txt not found next to installer.
    set /p API_KEY="  Paste OpenAI key now: "
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

echo  [2/6] Resolving Python...
call :resolve_python
if not defined PYTHON_EXE (
    echo  [*] Python not found. Installing Python 3.12 silently...
    call :install_python
    call :resolve_python
)
if not defined PYTHON_EXE (
    echo  [!] FATAL: Python installed but not found.
    echo      Check C:\Users\%USERNAME%\AppData\Local\Programs\Python or Program Files.
    pause
    exit /b 1
)
for %%F in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpF"
set "PYTHONW_EXE=%PYTHON_DIR%pythonw.exe"
if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=%PYTHON_EXE%"
echo  [OK] Python: %PYTHON_EXE%
echo  [OK] Pythonw: %PYTHONW_EXE%
echo.

echo  [3/6] Installing Python packages...
"%PYTHON_EXE%" -m pip --disable-pip-version-check install --upgrade pip
if errorlevel 1 (
    echo  [!] pip upgrade failed.
    pause
    exit /b 1
)
"%PYTHON_EXE%" -m pip --disable-pip-version-check install openai sounddevice soundfile keyboard pyperclip pyautogui numpy scipy
if errorlevel 1 (
    echo  [!] Package installation failed.
    pause
    exit /b 1
)
echo  [OK] Packages installed.
echo.

echo  [4/6] Installing app files...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if exist "%~dp0lavrentiy.py" (
    copy /Y "%~dp0lavrentiy.py" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0dashboard.html" "%INSTALL_DIR%\" >nul
    if exist "%~dp0lavrentiy.ico" copy /Y "%~dp0lavrentiy.ico" "%INSTALL_DIR%\" >nul
) else (
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

echo  [5/6] Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$target='%INSTALL_DIR%\lavrentiy.bat';" ^
  "$work='%INSTALL_DIR%';" ^
  "$name='Lavrentiy.lnk';" ^
  "$paths=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('CommonDesktopDirectory'));" ^
  "$ok=$false;" ^
  "$ico='%INSTALL_DIR%\lavrentiy.ico';" ^
  "foreach($d in $paths){ if([string]::IsNullOrWhiteSpace($d)){continue}; if(!(Test-Path $d)){continue}; $lnk=Join-Path $d $name; $ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut($lnk); $s.TargetPath=$target; $s.WorkingDirectory=$work; $s.Description='Lavrentiy Voice Engine'; if(Test-Path $ico){$s.IconLocation=$ico+',0'}else{$s.IconLocation=$target}; $s.Save(); if(Test-Path $lnk){$ok=$true; break} };" ^
  "if(-not $ok){ throw 'Shortcut creation failed' }"
if errorlevel 1 (
    echo  [!] Shortcut creation failed.
    echo      Launcher is still available at: %INSTALL_DIR%\lavrentiy.bat
    pause
    exit /b 1
)
echo  [OK] Shortcut created.
echo.

echo  [6/6] Verifying launcher...
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
echo  ==========================================
echo.
pause
exit /b 0

:download_fail
echo  [!] Failed to download required files.
pause
exit /b 1

:install_python
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.2/python-3.12.2-amd64.exe' -OutFile '%TEMP_PY%'"
if errorlevel 1 (
    echo  [!] Could not download Python installer.
    exit /b 1
)
start /wait "" "%TEMP_PY%" /quiet InstallAllUsers=1 Include_pip=1 PrependPath=0
if errorlevel 1 (
    echo  [*] All-users install failed, trying per-user install...
    start /wait "" "%TEMP_PY%" /quiet InstallAllUsers=0 Include_pip=1 PrependPath=0
)
exit /b 0

:resolve_python
set "PYTHON_EXE="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if exist "%%P" if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE exit /b 0
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $c=@(); $roots=@('HKLM:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore','HKCU:\SOFTWARE\Python\PythonCore'); foreach($r in $roots){ if(Test-Path $r){ Get-ChildItem $r | ForEach-Object { $i=(Get-ItemProperty -Path ($_.PSPath + '\InstallPath')).'(default)'; if($i){ $c += (Join-Path $i 'python.exe') } } } }; $patterns=@('$env:LocalAppData\Programs\Python\Python*\python.exe','$env:LocalAppData\Python\pythoncore-*\python.exe','C:\Program Files\Python*\python.exe','C:\Program Files (x86)\Python*\python.exe','C:\Python*\python.exe'); foreach($p in $patterns){ $c += Get-ChildItem -Path $ExecutionContext.InvokeCommand.ExpandString($p) -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName }; $c = $c | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique; $best = $c | Sort-Object { try { [version](Get-Item $_).VersionInfo.ProductVersion } catch { [version]'0.0' } } -Descending | Select-Object -First 1; if($best){ $best }"`) do (
    if exist "%%P" if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
exit /b 0
