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
import webbrowser

import webview
import pystray
from PIL import Image

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PY  = os.path.join(SCRIPT_DIR, "lavrentiy.py")
ICON_PATH  = os.path.join(SCRIPT_DIR, "lavrentiy.ico")
READY_URL    = "http://127.0.0.1:7878/api/state"
ONBOARD_URL  = "http://localhost:7878/"

# Splash HTML — loads instantly, no server needed. Shown while engine boots.
SPLASH_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@900&family=JetBrains+Mono:wght@400;600&display=swap');
html,body{height:100%;background:#1a1a1e;font-family:'JetBrains Mono',monospace;color:#d4d4d8;overflow:hidden;}
.wrap{height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px;}
.brand-plate{
  background:linear-gradient(180deg,#2a2a2a 0%,#1a1a1a 100%);
  border:1px solid rgba(255,255,255,0.08);border-radius:4px;
  box-shadow:0 2px 8px rgba(0,0,0,0.4),inset 0 1px 0 rgba(255,255,255,0.05);
  padding:18px 40px 14px;text-align:center;position:relative;margin-bottom:48px;
}
.brand-plate::before,.brand-plate::after,.scr-bl,.scr-br{
  content:'';position:absolute;width:6px;height:6px;border-radius:50%;
  background:radial-gradient(circle at 38% 38%,#ffe0a0,#c4956a 50%,#8a7060);
  box-shadow:inset 0 -1px 1px rgba(0,0,0,0.4),0 1px 2px rgba(0,0,0,0.5);
}
.brand-plate::before{top:6px;left:8px;}.brand-plate::after{top:6px;right:8px;}
.scr-bl{bottom:6px;left:8px;}.scr-br{bottom:6px;right:8px;}
.brand-cyr{font-family:'Playfair Display',serif;font-size:28px;font-weight:900;letter-spacing:4px;
  background:linear-gradient(180deg,#d4a574 0%,#c4956a 40%,#b8855a 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;line-height:1.2;}
.brand-eng{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:6px;color:rgba(255,255,255,0.45);text-transform:uppercase;margin-top:4px;}
.eq-wrap{display:flex;align-items:flex-end;gap:5px;height:48px;margin-bottom:32px;}
.eq-wrap span{display:block;width:4px;background:linear-gradient(180deg,#ee5a24 0%,#b91c1c 100%);border-radius:2px;
  box-shadow:0 0 6px rgba(238,90,36,0.4);transform-origin:center bottom;animation:eq 1.1s ease-in-out infinite;}
.eq-wrap span:nth-child(1){height:20px;animation-delay:-0.05s;}
.eq-wrap span:nth-child(2){height:34px;animation-delay:-0.25s;}
.eq-wrap span:nth-child(3){height:48px;animation-delay:-0.55s;}
.eq-wrap span:nth-child(4){height:42px;animation-delay:-0.15s;}
.eq-wrap span:nth-child(5){height:28px;animation-delay:-0.75s;}
.eq-wrap span:nth-child(6){height:36px;animation-delay:-0.40s;}
.eq-wrap span:nth-child(7){height:22px;animation-delay:-0.00s;}
@keyframes eq{0%,100%{transform:scaleY(0.25);}50%{transform:scaleY(1.0);}}
.status{font-size:9px;letter-spacing:3px;color:#888;text-transform:uppercase;min-height:14px;}
.status .dots::after{content:'';animation:dots 1.2s steps(4,end) infinite;}
@keyframes dots{0%{content:'';}25%{content:'.';}50%{content:'..';}75%{content:'...';}}
</style></head><body><div class="wrap">
<div class="brand-plate"><span class="scr-bl"></span><span class="scr-br"></span>
<div class="brand-cyr">Лаврентий</div><div class="brand-eng">LAVRENTIY</div></div>
<div class="eq-wrap"><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
<div class="status"><span id="status-text">Spawning engine</span><span class="dots"></span></div>
</div><script>
function setStatus(txt){var el=document.getElementById('status-text');if(el)el.textContent=txt;}
// Fallback timer in case Python doesn't push updates
var stages=['Spawning engine','Loading audio pipeline','Initializing speech recognition','Loading your voice profile','Registering hotkeys','Starting HTTP server','Preparing dashboard','Almost there'];
var i=0;
window._stageTimer=setInterval(function(){i++;if(i<stages.length)setStatus(stages[i]);},1400);
</script></body></html>"""

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


# ── JS API (exposed to page as window.pywebview.api) ─────────────────────────

class Api:
    def open_google_signin(self):
        """Open Google sign-in page in the system browser."""
        webbrowser.open("http://localhost:7878/auth/google")


# ── Entry point ───────────────────────────────────────────────────────────────

def _splash_status(win, text):
    """Push a status line to the splash screen. Silent on failure (splash might be gone)."""
    try:
        # Stop the fallback timer and set text explicitly
        win.evaluate_js(f"if(window._stageTimer)clearInterval(window._stageTimer); setStatus({text!r});")
    except Exception:
        pass


def boot(win):
    """Runs in a background thread after the splash window is shown.
    Starts the engine, waits for it, then navigates the window to the dashboard."""
    _splash_status(win, "Spawning engine process")
    print("[desktop] Starting engine subprocess...")
    start_engine()
    _splash_status(win, "Loading audio pipeline")
    time.sleep(0.3)  # let subprocess begin imports
    print("[desktop] Waiting for HTTP server on :7878 ...")
    # Poll faster than wait_for_engine so we can update status messages
    deadline = time.time() + 20
    elapsed = 0
    while time.time() < deadline:
        try:
            urllib.request.urlopen(READY_URL, timeout=1)
            break
        except Exception:
            elapsed = time.time() - (deadline - 20)
            if elapsed > 1.5 and elapsed < 3:
                _splash_status(win, "Initializing speech recognition")
            elif elapsed > 3 and elapsed < 4.5:
                _splash_status(win, "Registering F9 hotkey")
            elif elapsed > 4.5 and elapsed < 6:
                _splash_status(win, "Loading your voice profile")
            elif elapsed > 6 and elapsed < 7.5:
                _splash_status(win, "Starting dashboard server")
            elif elapsed > 7.5:
                _splash_status(win, "Almost there")
            time.sleep(0.3)
    else:
        # timed out
        print("[desktop] ERROR: engine did not respond. Check lavrentiy.py.",
              file=sys.stderr)
        if engine_proc is not None:
            engine_proc.kill()
        try:
            win.load_html("<html><body style='background:#1a1a1e;color:#dc2626;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-size:14px;'>Engine failed to start. Check lavrentiy.py.</body></html>")
        except Exception:
            pass
        return
    _splash_status(win, "Loading dashboard")
    print("[desktop] Engine ready — loading dashboard.")
    try:
        win.load_url(ONBOARD_URL)
    except Exception as e:
        print(f"[desktop] load_url failed: {e}", file=sys.stderr)


def main():
    global window

    # System tray runs in a daemon thread so it doesn't block main
    tray_thread = threading.Thread(target=build_and_run_tray, daemon=True)
    tray_thread.start()

    api = Api()

    # Create the window with inline splash HTML — appears IMMEDIATELY
    window = webview.create_window(
        title="LAVRENTIY",
        html=SPLASH_HTML,            # splash shows instantly, no server needed
        width=1100,
        height=750,
        min_size=(800, 600),
        background_color="#1a1a1e",
        resizable=True,
        text_select=True,
        js_api=api,
    )
    window.events.closing += on_closing

    # webview.start(func, window) runs func in a background thread AFTER the
    # GUI loop starts. boot() spawns the engine subprocess, waits for it, then
    # navigates the window to the dashboard once ready.
    webview.start(boot, window, debug=False)

    # Fell through — webview.start has returned (window destroyed)
    if not _shutdown.is_set():
        quit_app()

    sys.exit(0)


if __name__ == "__main__":
    main()
