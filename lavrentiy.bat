@echo off
setlocal EnableExtensions
set "INSTALL_DIR=%~dp0"
set "SCRIPT=%INSTALL_DIR%lavrentiy.py"
set "PYTHONW_EXE="

for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if exist "%%P" (
        for %%F in ("%%P") do set "PYTHONW_EXE=%%~dpFpythonw.exe"
    )
)

if not defined PYTHONW_EXE (
    for %%d in (
        "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
        "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
        "C:\Program Files\Python312\pythonw.exe"
        "C:\Program Files\Python313\pythonw.exe"
        "C:\Program Files\Python314\pythonw.exe"
    ) do (
        if exist %%d if not defined PYTHONW_EXE set "PYTHONW_EXE=%%~d"
    )
)

if defined PYTHONW_EXE (
    start "" "%PYTHONW_EXE%" "%SCRIPT%"
    timeout /t 3 /nobreak >nul
    start "" "http://localhost:7878"
    exit /b 0
)

echo Python not found. Run installer first.
pause
exit /b 1
