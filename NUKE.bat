@echo off
title LAVRENTIY CLEANUP
echo.
echo ============================================
echo   LAVRENTIY - Full Cleanup
echo ============================================
echo.

:: ── Kill any running Lavrentiy processes ──────────────────────
echo [1/3] Killing running processes...

for /f "tokens=2" %%i in ('wmic process where "name='pythonw.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /pid %%i /f >nul 2>&1
)
for /f "tokens=2" %%i in ('wmic process where "name='python.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /pid %%i /f >nul 2>&1
)

echo Done.

:: ── Remove old installed copy ─────────────────────────────────
echo [2/3] Removing old installation...

if exist "%USERPROFILE%\Lavrentiy" (
    rmdir /s /q "%USERPROFILE%\Lavrentiy"
    echo Removed: %USERPROFILE%\Lavrentiy
) else (
    echo Not found: %USERPROFILE%\Lavrentiy
)

:: ── Remove desktop shortcut ───────────────────────────────────
echo [3/3] Removing desktop shortcut...

set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%PUBLIC%\Desktop"

if exist "%DESKTOP%\Lavrentiy.lnk" (
    del /f "%DESKTOP%\Lavrentiy.lnk"
    echo Removed: Lavrentiy.lnk
) else (
    echo Not found: Lavrentiy.lnk
)

if exist "%DESKTOP%\Lavrentiy Desktop.lnk" (
    del /f "%DESKTOP%\Lavrentiy Desktop.lnk"
    echo Removed: Lavrentiy Desktop.lnk
)

echo.
echo ============================================
echo   All clear. Safe to install fresh.
echo ============================================
echo.
pause
