"""Lavrentiy native window via pywebview + WebView2 (Edge Chromium).
Replaces the PySide6+QWebEngineView variant. Same dashboard, modern engine,
~50 MB bundle instead of ~1 GB, no flicker class of bugs.
"""
import sys
import time
import threading
import urllib.request
import webbrowser
from pathlib import Path

# === JS-callable API exposed as window.pywebview.api in the dashboard.
# dashboard.html checks for window.pywebview.api.open_google_signin and calls
# it for Google OAuth (Google blocks OAuth in embedded webviews — must route
# through the system default browser via webbrowser.open).
class JSAPI:
    # MUST be "localhost", never "127.0.0.1" — Google treats them as different
    # origins and only http://localhost:7878 is an authorized JavaScript origin
    # on the OAuth client. See the same note in lavrentiy_launcher.py.
    SIGNIN_URL = 'http://localhost:7878/auth/google'

    def open_google_signin(self):
        try:
            webbrowser.open(self.SIGNIN_URL, new=2)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}

# === Path setup (mirrors lavrentiy_app.py so the bundled lavrentiy.py is found)
if hasattr(sys, "_MEIPASS"):
    REPO = Path(sys._MEIPASS)
else:
    REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# === Load lavrentiy engine (same pattern as PySide6 variant)
import importlib.util
spec = importlib.util.spec_from_file_location('lavrentiy', str(REPO / 'lavrentiy.py'))
lavrentiy = importlib.util.module_from_spec(spec)
sys.modules['lavrentiy'] = lavrentiy
spec.loader.exec_module(lavrentiy)

# === Start engine + HTTP server + tray in a NON-daemon thread.
# Non-daemon means closing the pywebview window doesn't kill the engine —
# user controls quit via the tray icon (right-click → Quit Lavrentiy).
# run_http_server=True activates the system tray (which has the Quit menu);
# the engine's tray code has the auto-open-browser disabled, so no Chrome flash.
def _run_engine():
    lavrentiy.start_engine(run_http_server=True, block=True)

threading.Thread(target=_run_engine, name="lavrentiy-engine", daemon=False).start()

# === Wait for /api/state to respond (HTTP server boot)
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:7878/api/state", timeout=0.5)
        break
    except Exception:
        time.sleep(0.25)

# === Open the dashboard in a native window via WebView2 (Edge Chromium)
import webview
webview.create_window(
    title='Lavrentiy',
    url='http://127.0.0.1:7878',
    width=1280,
    height=820,
    resizable=True,
    confirm_close=False,
    js_api=JSAPI(),
)
webview.start(gui='edgechromium')
