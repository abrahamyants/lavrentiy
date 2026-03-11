@echo off
setlocal EnableExtensions

echo === TEST: All 3 probes (no short-circuit) ===
echo.

:: ─── Probe 1: py launcher ───
set "P1="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if exist "%%P" set "P1=%%P"
)
if defined P1 (echo [Probe 1] py launcher: %P1%) else (echo [Probe 1] py launcher: NOT FOUND)

:: ─── Probe 2a: ExecutablePath (named value) ───
set "P2A="
for %%V in (3.12 3.13 3.14) do (
    for %%H in (
        "HKLM\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKCU\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore\%%V\InstallPath"
    ) do (
        if not defined P2A (
            for /f "tokens=2*" %%a in ('reg query %%H /v ExecutablePath 2^>nul') do (
                if exist "%%b" set "P2A=%%b"
            )
        )
    )
)
if defined P2A (echo [Probe 2a] ExecutablePath: %P2A%) else (echo [Probe 2a] ExecutablePath: NOT FOUND)

:: ─── Probe 2b: (Default) via findstr — replaces flaky /ve ───
set "P2B="
for %%V in (3.12 3.13 3.14) do (
    for %%H in (
        "HKLM\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKCU\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore\%%V\InstallPath"
    ) do (
        if not defined P2B (
            for /f "tokens=2*" %%a in ('reg query %%H 2^>nul ^| findstr /c:"(Default)"') do (
                if exist "%%bpython.exe" (
                    set "P2B=%%bpython.exe"
                ) else if exist "%%b\python.exe" (
                    set "P2B=%%b\python.exe"
                )
            )
        )
    )
)
if defined P2B (echo [Probe 2b] Default findstr: %P2B%) else (echo [Probe 2b] Default findstr: NOT FOUND)

:: ─── Probe 2c: OLD /ve for comparison ───
set "P2C="
for %%V in (3.12 3.13 3.14) do (
    for %%H in (
        "HKLM\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKCU\SOFTWARE\Python\PythonCore\%%V\InstallPath"
        "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore\%%V\InstallPath"
    ) do (
        if not defined P2C (
            for /f "tokens=2*" %%a in ('reg query %%H /ve 2^>nul') do (
                if exist "%%bpython.exe" (
                    set "P2C=%%bpython.exe"
                ) else if exist "%%b\python.exe" (
                    set "P2C=%%b\python.exe"
                )
            )
        )
    )
)
if defined P2C (echo [Probe 2c] OLD /ve:         %P2C%) else (echo [Probe 2c] OLD /ve:         NOT FOUND ^(expected — this is the bug^))

:: ─── Probe 3: Hardcoded paths ───
set "P3="
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
    if exist %%d if not defined P3 set "P3=%%~d"
)
if defined P3 (echo [Probe 3]  Hardcoded:       %P3%) else (echo [Probe 3]  Hardcoded:       NOT FOUND)

echo.
echo --- Summary ---
echo   Probe 1 (py launcher):     %P1%
echo   Probe 2a (ExecutablePath):  %P2A%
echo   Probe 2b (findstr Default): %P2B%
echo   Probe 2c (OLD /ve):         %P2C%
echo   Probe 3 (hardcoded):        %P3%
echo.

:: ─── VBScript Desktop path ───
echo --- VBScript Desktop path ---
> "%TEMP%\test_desktop.vbs" (
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo WScript.Echo oWS.SpecialFolders^("Desktop"^)
)
for /f "usebackq delims=" %%r in (`cscript //nologo "%TEMP%\test_desktop.vbs" 2^>nul`) do echo   Desktop: %%r
del "%TEMP%\test_desktop.vbs" >nul 2>&1

echo.
echo === DONE ===
