"""
Build a portable Lavrentiy package for distribution.
Downloads Python embeddable, installs pinned dependencies, copies engine files,
and creates START/STOP/UPDATE launchers.

Run: python build_portable.py
Output: ./portable/ folder — zip and distribute.
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import textwrap

# --- Config ---
PYTHON_VERSION = "3.13.3"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
REQUIREMENTS_FILE = "requirements.portable.txt"

# Engine files to copy into portable/engine/
ENGINE_FILES = [
    "lavrentiy.py",
    "dashboard.html",
    "mobile.html",
    "onboard.html",
    "desktop.py",
    "lavrentiy.ico",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTABLE_DIR = os.path.join(SCRIPT_DIR, "portable")
PYTHON_DIR = os.path.join(PORTABLE_DIR, "python")
ENGINE_DIR = os.path.join(PORTABLE_DIR, "engine")

# GitHub raw URL for UPDATE.bat (update if repo moves)
GITHUB_RAW = "https://raw.githubusercontent.com/gugosf114/lavrentiy/main"


def download(url, dest):
    print(f"  Downloading {url.split('/')[-1]}...")
    urllib.request.urlretrieve(url, dest)
    print(f"  Saved to {dest}")


def get_version():
    """Get version from git tag or fallback to date."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True, text=True, cwd=SCRIPT_DIR
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    from datetime import datetime
    return f"dev-{datetime.now().strftime('%Y%m%d')}"


def main():
    print("=" * 60)
    print("  LAVRENTIY PORTABLE BUILDER")
    print("=" * 60)

    # Clean previous build
    if os.path.exists(PORTABLE_DIR):
        print(f"\nRemoving previous build at {PORTABLE_DIR}...")
        shutil.rmtree(PORTABLE_DIR)

    os.makedirs(PYTHON_DIR, exist_ok=True)
    os.makedirs(ENGINE_DIR, exist_ok=True)

    # Step 1: Download Python embeddable
    print(f"\n[1/6] Downloading Python {PYTHON_VERSION} embeddable...")
    zip_path = os.path.join(PORTABLE_DIR, "python_embed.zip")
    download(PYTHON_EMBED_URL, zip_path)

    print("  Extracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(PYTHON_DIR)
    os.remove(zip_path)

    # Step 2: Enable pip in embeddable Python
    print("\n[2/6] Enabling pip support...")
    pth_files = [f for f in os.listdir(PYTHON_DIR) if f.endswith("._pth")]
    if pth_files:
        pth_path = os.path.join(PYTHON_DIR, pth_files[0])
        with open(pth_path, "r") as f:
            content = f.read()
        content = content.replace("#import site", "import site")
        with open(pth_path, "w") as f:
            f.write(content)
        print(f"  Patched {pth_files[0]}")

    # Download and run get-pip.py
    pip_path = os.path.join(PORTABLE_DIR, "get-pip.py")
    download(GET_PIP_URL, pip_path)

    python_exe = os.path.join(PYTHON_DIR, "python.exe")
    print("  Installing pip...")
    subprocess.run(
        [python_exe, pip_path, "--no-warn-script-location"],
        cwd=PYTHON_DIR,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    os.remove(pip_path)

    # Install setuptools immediately — needed as build backend for source-dist packages
    subprocess.run(
        [python_exe, "-m", "pip", "install", "setuptools", "--no-warn-script-location", "-q"],
        cwd=PYTHON_DIR,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Step 2.5: Pre-install pythonnet (release build can't compile on Python 3.12+)
    print("\n[2.5/6] Installing pythonnet pre-release (required by pywebview)...")
    result = subprocess.run(
        [python_exe, "-m", "pip", "install", "--pre", "pythonnet",
         "--no-warn-script-location", "-q"],
        cwd=PYTHON_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  WARNING: pythonnet pre-release install failed:\n{result.stderr[:300]}")
    else:
        print("  pythonnet installed.")

    # Step 3: Install pinned dependencies
    req_path = os.path.join(SCRIPT_DIR, REQUIREMENTS_FILE)
    if not os.path.exists(req_path):
        print(f"\n  ERROR: {REQUIREMENTS_FILE} not found!")
        sys.exit(1)

    print(f"\n[3/6] Installing dependencies from {REQUIREMENTS_FILE}...")
    result = subprocess.run(
        [python_exe, "-m", "pip", "install", "-r", req_path,
         "--no-warn-script-location", "-q"],
        cwd=PYTHON_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  WARNING: pip install failed:\n{result.stderr[:500]}")
    else:
        print("  All dependencies installed.")

    # Step 4: Copy engine files
    print("\n[4/6] Copying engine files...")
    for fname in ENGINE_FILES:
        src = os.path.join(SCRIPT_DIR, fname)
        if not os.path.exists(src):
            print(f"  SKIP: {fname} (not found)")
            continue
        dst = os.path.join(ENGINE_DIR, fname)
        shutil.copy2(src, dst)
        size_kb = os.path.getsize(dst) // 1024
        print(f"  {fname} ({size_kb} KB)")

    # Step 5: Write VERSION.txt
    version = get_version()
    print(f"\n[5/6] Version: {version}")
    with open(os.path.join(ENGINE_DIR, "VERSION.txt"), "w") as f:
        f.write(version)

    # Step 6: Create launchers
    print("\n[6/6] Creating launchers...")

    # --- START.bat ---
    start_bat = os.path.join(PORTABLE_DIR, "START.bat")
    with open(start_bat, "w") as f:
        f.write(textwrap.dedent("""\
            @echo off
            title Lavrentiy
            cd /d "%~dp0engine"

            echo Starting Lavrentiy...
            start "" /B "%~dp0python\\pythonw.exe" "%~dp0engine\\desktop.py"

            echo.
            echo ============================================
            echo   Lavrentiy is starting.
            echo   The window will appear in a few seconds.
            echo   Use the system tray icon to show/hide/quit.
            echo ============================================
            echo.
        """))

    # --- STOP.bat ---
    stop_bat = os.path.join(PORTABLE_DIR, "STOP.bat")
    with open(stop_bat, "w") as f:
        f.write(textwrap.dedent("""\
            @echo off
            cd /d "%~dp0"
            echo Stopping Lavrentiy...

            REM Try PID file first (safe — only kills our process)
            if exist "engine\\lavrentiy.pid" (
                set /p PID=<engine\\lavrentiy.pid
                taskkill /pid %PID% /f >nul 2>&1
                if %errorlevel% equ 0 (
                    echo Stopped (PID %PID%).
                ) else (
                    echo PID %PID% not found — may have already exited.
                )
                del "engine\\lavrentiy.pid"
            ) else (
                echo No PID file found. Trying to find Lavrentiy process...
                REM Fallback: kill pythonw.exe running lavrentiy.py specifically
                for /f "tokens=2" %%i in ('wmic process where "name='pythonw.exe' and commandline like '%%lavrentiy%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
                    taskkill /pid %%i /f >nul 2>&1
                    echo Stopped (PID %%i).
                )
            )

            echo Done.
            timeout /t 2 /nobreak > nul
        """))

    # --- UPDATE.bat ---
    update_bat = os.path.join(PORTABLE_DIR, "UPDATE.bat")
    with open(update_bat, "w") as f:
        f.write(textwrap.dedent(f"""\
            @echo off
            cd /d "%~dp0"
            echo ============================================
            echo   LAVRENTIY UPDATE
            echo ============================================
            echo.
            echo Downloading latest engine files from GitHub...

            powershell -Command "Invoke-WebRequest -Uri '{GITHUB_RAW}/lavrentiy.py' -OutFile 'engine\\lavrentiy.py'"
            if %errorlevel% neq 0 (
                echo FAILED to download lavrentiy.py
                pause
                exit /b 1
            )
            echo   Updated: lavrentiy.py

            powershell -Command "Invoke-WebRequest -Uri '{GITHUB_RAW}/dashboard.html' -OutFile 'engine\\dashboard.html'"
            if %errorlevel% neq 0 (
                echo FAILED to download dashboard.html
                pause
                exit /b 1
            )
            echo   Updated: dashboard.html

            powershell -Command "Invoke-WebRequest -Uri '{GITHUB_RAW}/mobile.html' -OutFile 'engine\\mobile.html'"
            echo   Updated: mobile.html

            echo.
            echo Update complete. Restart with START.bat.
            echo.
            pause
        """))

    # Final summary
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(PORTABLE_DIR):
        for fname in filenames:
            total_size += os.path.getsize(os.path.join(dirpath, fname))
    total_mb = total_size / (1024 * 1024)

    print("\n" + "=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    print(f"  Location: {PORTABLE_DIR}")
    print(f"  Size: {total_mb:.0f} MB")
    print(f"  Version: {version}")
    print()
    print("  Contents:")
    print("    START.bat     - Launch engine + open dashboard")
    print("    STOP.bat      - Stop engine (by PID, safe)")
    print("    UPDATE.bat    - Pull latest engine from GitHub")
    print("    python/       - Portable Python + pinned dependencies")
    print("    engine/       - lavrentiy.py + dashboard.html + desktop.py + onboard.html")
    print()
    print("  To distribute: zip the 'portable' folder.")
    print("  First run shows onboard screen (own key or Google Sign-In).")
    print("=" * 60)


if __name__ == "__main__":
    main()
