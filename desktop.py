#!/usr/bin/env python3
"""desktop.py — Lavrentiy Desktop Wrapper

Starts lavrentiy.py as a subprocess, waits for its HTTP server on :7878,
then opens a native pywebview window showing the existing dashboard.
A pystray system-tray icon lets the user show/hide/quit.

Usage:
    python desktop.py          (shows console — good for debugging)
    pythonw desktop.py         (silent — production mode via desktop.bat)
"""

import os
import sys
import time
import threading
import subprocess
import urllib.request

import webview
import pystray
from PIL import Image

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PY  = os.path.join(SCRIPT_DIR, "lavrentiy.py")
ICON_PATH  = os.path.join(SCRIPT_DIR, "lavrentiy.ico")
READY_URL    = "http://127.0.0.1:7878/api/state"
ONBOARD_URL  = "http://127.0.0.1:7878/onboard"

# ── Shared state (touched from main + tray threads) ───────────────────────────
engine_proc = None   # subprocess.Popen
window      = None   # webview.Window
tray_icon   = None   # pystray.Icon
_quitting   = False  # set True to let the closing event allow real close
_shutdown   = threading.Event()


# ── Engine subprocess ─────────────────────────────────────────────────────────

def start_engine():
    global engine_proc
    engine_proc = subprocess.Popen(
        [sys.executable, ENGINE_PY],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=SCRIPT_DIR,
    )


def wait_for_engine(timeout=20):
    """Poll /api/state until it responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(READY_URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ── Shutdown ──────────────────────────────────────────────────────────────────

def quit_app(icon=None, item=None):
    """Clean shutdown: stop tray, kill engine, destroy window."""
    global engine_proc, tray_icon, _quitting
    if _shutdown.is_set():
        return
    _shutdown.set()
    _quitting = True

    if tray_icon is not None:
        try:
            tray_icon.stop()
        except Exception:
            pass
        tray_icon = None

    if engine_proc is not None:
        engine_proc.terminate()
        try:
            engine_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            engine_proc.kill()
        engine_proc = None

    if window is not None:
        try:
            window.destroy()  # unblocks webview.start() on the main thread
        except Exception:
            pass


# ── Window events ─────────────────────────────────────────────────────────────

def on_closing():
    """Intercept the X button: hide to tray instead of exiting."""
    if _quitting:
        return True   # allow the real destroy() call from quit_app
    if window is not None:
        window.hide()
    return False      # cancel the close


# ── Tray callbacks ────────────────────────────────────────────────────────────

def show_dashboard(icon=None, item=None):
    if window is not None:
        window.show()


def build_and_run_tray():
    """Build the pystray icon and block this thread on its event loop."""
    global tray_icon
    img = Image.open(ICON_PATH)
    menu = pystray.Menu(
        pystray.MenuItem("Show Dashboard", show_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    tray_icon = pystray.Icon("lavrentiy", img, "LAVRENTIY", menu=menu)
    tray_icon.run()   # blocks until tray_icon.stop()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global window

    print("[desktop] Starting engine subprocess...")
    start_engine()

    print("[desktop] Waiting for HTTP server on :7878 ...")
    if not wait_for_engine(timeout=20):
        print("[desktop] ERROR: engine did not respond. Check lavrentiy.py.",
              file=sys.stderr)
        if engine_proc is not None:
            engine_proc.kill()
        sys.exit(1)
    print("[desktop] Engine ready.")

    # System tray runs in a daemon thread so it doesn't block main
    tray_thread = threading.Thread(target=build_and_run_tray, daemon=True)
    tray_thread.start()

    # Create the native window (not yet visible — webview.start shows it)
    window = webview.create_window(
        title="LAVRENTIY",
        url=ONBOARD_URL,
        width=1100,
        height=750,
        min_size=(800, 600),
        background_color="#1a1a2e",
        resizable=True,
        text_select=True,
    )
    window.events.closing += on_closing

    # Blocks until window.destroy() is called
    webview.start(debug=False)

    # Fell through (e.g. window destroyed some other way) — clean up
    if not _shutdown.is_set():
        quit_app()

    sys.exit(0)


if __name__ == "__main__":
    main()
