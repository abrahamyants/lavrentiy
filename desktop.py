#!/usr/bin/env python3
"""desktop.py — Lavrentiy Desktop Wrapper

Starts lavrentiy.py as a subprocess, waits for its HTTP server on :7878,
then opens a native pywebview window showing the existing dashboard.
Single-instance (Windows mutex). Closing the window terminates the engine
subprocess cleanly.

Usage:
    python desktop.py          (shows console — good for debugging)
    pythonw desktop.py         (silent — production mode via VBS / .lnk)
"""

import os
import sys
import time
import json
import threading
import subprocess
import urllib.request
import webbrowser

# Headless mode (pythonw / hidden console). Without this, print() calls fail
# under pythonw.exe because sys.stdout is None, which silently kills pywebview's
# init thread before the window is created.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# Single-instance mutex — prevents duplicate desktop.py processes from stacking
# up with zombie windows (the failure mode that put PIDs 17464 + 12668 on
# screen with MainWindowHandle=0). Same pattern the engine uses; exit before
# importing webview if another copy is already alive.
import ctypes
_kernel32 = ctypes.windll.kernel32
_desktop_mutex = _kernel32.CreateMutexW(None, True, "Global\\LAVRENTIY_DESKTOP_SINGLE_INSTANCE")
if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    _kernel32.CloseHandle(_desktop_mutex)
    # Another desktop.py is already alive (typically: post-install auto-launch
    # set up the engine + pywebview, then the user double-clicked the desktop
    # shortcut). Don't silently exit — the user expects clicking the icon to
    # show the app. Open the dashboard in the default browser so they see UI
    # immediately. Works whether the prior pywebview window is still up,
    # minimized, or got closed but the engine kept running.
    try:
        webbrowser.open("http://127.0.0.1:7878/")
    except Exception:
        pass
    sys.exit(0)

import webview

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PY  = os.path.join(SCRIPT_DIR, "lavrentiy.py")
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

# ── Shared state ──────────────────────────────────────────────────────────────
engine_proc = None   # subprocess.Popen
window      = None   # webview.Window
_shutdown   = threading.Event()


# ── Engine subprocess ─────────────────────────────────────────────────────────

def start_engine():
    global engine_proc
    # Capture engine stderr to a file so crashes leave a trace. APPEND so
    # restart cycles preserve history (truncate would erase the crash trace
    # right after the restart loads).
    err_log = open(os.path.join(SCRIPT_DIR, "engine_err.log"), "a", buffering=1)
    out_log = open(os.path.join(SCRIPT_DIR, "engine_out.log"), "a", buffering=1)
    engine_proc = subprocess.Popen(
        [sys.executable, "-u", ENGINE_PY],
        stdout=out_log,
        stderr=err_log,
        cwd=SCRIPT_DIR,
    )


def _watchdog_loop():
    """Auto-restart the engine subprocess if it dies. Runs as a daemon thread.

    Polls engine_proc.poll() every 3 seconds. On unexpected death (poll
    returns non-None and shutdown wasn't requested), waits 2s for any
    held mutex to release, then re-launches via start_engine() and reloads
    the dashboard URL.

    This is a band-aid against the silent engine-death problem we're still
    diagnosing. Without it, a single crash takes the whole window with it.
    With it, the user sees a brief "reconnecting..." window then the engine
    is back. The lifecycle log + crash traces are still being collected for
    the actual root cause hunt.
    """
    global engine_proc
    while not _shutdown.is_set():
        time.sleep(3)
        if _shutdown.is_set():
            return
        if engine_proc is None:
            continue
        rc = engine_proc.poll()
        if rc is None:
            continue  # engine still alive, normal case
        # Engine died. Capture exit code, wait for mutex release, restart.
        try:
            sys.stderr.write(f"[watchdog] engine PID exited rc={rc} — restarting in 2s\n")
            sys.stderr.flush()
        except Exception:
            pass
        time.sleep(2)
        if _shutdown.is_set():
            return
        try:
            start_engine()
        except Exception as e:
            try:
                sys.stderr.write(f"[watchdog] restart failed: {e}\n")
                sys.stderr.flush()
            except Exception:
                pass
            continue
        # Re-poll for readiness, then reload the window.
        deadline = time.time() + 60
        while time.time() < deadline and not _shutdown.is_set():
            try:
                resp = urllib.request.urlopen(READY_URL, timeout=1)
                data = json.loads(resp.read().decode())
                if data.get("ready") or data.get("state") in ("idle", "recording", "processing"):
                    break
            except Exception:
                pass
            time.sleep(0.4)
        try:
            if window is not None:
                window.load_url(ONBOARD_URL)
        except Exception:
            pass


def wait_for_engine(timeout=60):
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

def quit_app():
    """Clean shutdown: kill engine subprocess, destroy window."""
    global engine_proc
    if _shutdown.is_set():
        return
    _shutdown.set()

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
    Starts the engine, polls /api/state for ready=true (engine reports its
    own boot_stage during the init window), shows that stage as live splash
    text, navigates to the dashboard only once ready."""
    # Force-show the window. pywebview creates the window with default-visible
    # but on some Windows configurations the OS reports IsWindowVisible=False
    # until something explicitly calls show(), and the user sees nothing on
    # screen even though the process tree shows the webview is alive. This
    # one-line call eliminates the dead-shortcut UX bug.
    try:
        win.show()
    except Exception:
        pass
    _splash_status(win, "starting engine")
    print("[desktop] Starting engine subprocess...")
    start_engine()
    print("[desktop] Polling /api/state for readiness...")
    # With the boot stub server, /api/state responds within ~1s of launch with
    # {ready: false, boot_stage: "..."}. We follow that stage live until
    # ready=true, then navigate to the full dashboard.
    deadline = time.time() + 90
    last_stage = None
    ready = False
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(READY_URL, timeout=1)
            data = json.loads(resp.read().decode())
            stage = data.get("boot_stage") or data.get("state") or "starting"
            if stage != last_stage:
                _splash_status(win, stage)
                print(f"[desktop] stage: {stage}")
                last_stage = stage
            if data.get("ready") or data.get("state") in ("idle", "recording", "processing"):
                ready = True
                break
        except Exception:
            if last_stage != "starting engine":
                _splash_status(win, "starting engine")
                last_stage = "starting engine"
        time.sleep(0.4)
    if not ready:
        print("[desktop] ERROR: engine did not report ready. Check lavrentiy.py.",
              file=sys.stderr)
        if engine_proc is not None:
            engine_proc.kill()
        try:
            win.load_html("<html><body style='background:#1a1a1e;color:#dc2626;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-size:14px;'>Engine failed to start. Check lavrentiy.py.</body></html>")
        except Exception:
            pass
        return
    _splash_status(win, "loading dashboard")
    print("[desktop] Engine ready — loading dashboard.")
    try:
        win.load_url(ONBOARD_URL)
    except Exception as e:
        print(f"[desktop] load_url failed: {e}", file=sys.stderr)
    # Start the engine watchdog AFTER the dashboard loads. Auto-restarts
    # the engine subprocess if it dies — band-aid until we find the root
    # cause of the silent crashes. Daemon thread, exits with main process.
    t = threading.Thread(target=_watchdog_loop, name="engine-watchdog", daemon=True)
    t.start()
    print("[desktop] watchdog started")


def main():
    global window

    api = Api()

    # Create the window with inline splash HTML — appears IMMEDIATELY.
    # No tray thread: pystray.Icon.run() requires the main thread (per its API
    # contract), and so does webview.start() on Windows. Running them together
    # scrambled both GUI loops — window object got created but never registered
    # with the OS (MainWindowHandle stayed 0). Tray is gone. X button = exit.
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
