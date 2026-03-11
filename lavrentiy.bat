@echo off
:: Try pythonw in PATH first
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0lavrentiy.py"
    goto :eof
)
:: Search common locations
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
    "C:\Program Files\Python312\pythonw.exe"
    "C:\Program Files\Python313\pythonw.exe"
    "C:\Program Files\Python314\pythonw.exe"
    "%LOCALAPPDATA%\Python\pythoncore-3.12-64\pythonw.exe"
    "%LOCALAPPDATA%\Python\pythoncore-3.13-64\pythonw.exe"
    "%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
) do (
    if exist %%d (
        start "" %%d "%~dp0lavrentiy.py"
        goto :eof
    )
)
:: Last resort — try python.exe (will show console window)
where python >nul 2>&1
if %errorlevel% equ 0 (
    start "" python "%~dp0lavrentiy.py"
    goto :eof
)
echo Python not found. Run install.bat first.
pause
