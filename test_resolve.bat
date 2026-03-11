@echo off
setlocal EnableExtensions

echo === TEST: resolve_python from install.bat ===
echo.

set "PYTHON_EXE="

:: Probe 1: py launcher
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if exist "%%P" if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
if defined PYTHON_EXE (
    echo [Probe 1] py launcher: %PYTHON_EXE%
    goto :found
)
echo [Probe 1] py launcher: not found

:: Probe 2: Registry
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
if defined PYTHON_EXE (
    echo [Probe 2] Registry: %PYTHON_EXE%
    goto :found
)
echo [Probe 2] Registry: not found

:: Probe 3: Hardcoded
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
if defined PYTHON_EXE (
    echo [Probe 3] Hardcoded: %PYTHON_EXE%
    goto :found
)
echo [Probe 3] Hardcoded: not found
echo [FAIL] No Python found anywhere.
goto :done

:found
for %%F in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpF"
set "PYTHONW_EXE=%PYTHON_DIR%pythonw.exe"
echo.
echo   PYTHON_EXE:  %PYTHON_EXE%
echo   PYTHON_DIR:  %PYTHON_DIR%
echo   PYTHONW_EXE: %PYTHONW_EXE%
if exist "%PYTHONW_EXE%" (echo   pythonw: EXISTS) else (echo   pythonw: MISSING)
echo.

echo --- VBScript Desktop path ---
> "%TEMP%\test_desktop.vbs" (
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo WScript.Echo oWS.SpecialFolders^("Desktop"^)
)
for /f "usebackq delims=" %%r in (`cscript //nologo "%TEMP%\test_desktop.vbs" 2^>nul`) do echo   Desktop: %%r
del "%TEMP%\test_desktop.vbs" >nul 2>&1

:done
echo.
echo === DONE ===
