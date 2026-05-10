"""Lavrentiy — single-file launcher (PyInstaller --onefile entry).

Imports lavrentiy.py (which starts the HTTP server + hotkey hook), then opens
the user's default browser to the dashboard once :7878 is accepting connections.

Self-contained: when frozen, all .py modules + data files (l1_packs/,
domain_packs/, lang_packs/, local/, dashboard.html, silero_vad.onnx, api keys,
faster-whisper model) are bundled inside the .exe and extracted to sys._MEIPASS
on launch. No install, no PATH, no internet needed to start. Internet is only
required for cloud API calls (whisper-1, gpt-4o, sonnet) during use.
"""
import os
import socket
import sys
import threading
import time
import webbrowser

DASHBOARD_PORT = 7878
DASHBOARD_URL = f"http://localhost:{DASHBOARD_PORT}/"


def _bundle_dir():
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _wait_for_port(port, timeout_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _open_browser_when_ready():
    if _wait_for_port(DASHBOARD_PORT):
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception:
            pass


def main():
    bundle = _bundle_dir()
    sys.path.insert(0, bundle)
    os.chdir(bundle)

    if os.environ.get("LAV_NO_BROWSER", "0") != "1":
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    import lavrentiy
    lavrentiy.start_engine(run_http_server=True, block=True)


if __name__ == "__main__":
    main()
