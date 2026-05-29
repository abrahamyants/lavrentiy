"""Lavrentiy — launcher (PyInstaller --onedir entry point).

Two launch modes:
  * Default — start engine + HTTP server, let the .vbs wrapper open the
    dashboard in Edge/Chrome --app= chromeless mode (LAV_NO_BROWSER=1).
    Used by Lavrentiy.vbs.
  * --native — start engine + HTTP server, then open the dashboard in a
    pywebview/WebView2 native window. No external browser involved.
    Used by Lavrentiy-Native.vbs.

Self-contained: when frozen, all .py modules + data files (l1_packs/,
domain_packs/, lang_packs/, local/, dashboard.html, silero_vad.onnx, api keys,
faster-whisper model) are bundled alongside Lavrentiy.exe in the output
directory under _internal/. Internet only required for cloud API calls
(whisper-1, gpt-4o, sonnet) during use.
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


class _JSAPI:
    """JS bridge exposed as window.pywebview.api to dashboard.html.
    Google blocks OAuth in embedded webviews, so the dashboard calls
    open_google_signin() which we route through the system default browser."""

    def open_google_signin(self):
        try:
            webbrowser.open('http://127.0.0.1:7878/auth/google', new=2)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}


def _run_native_window():
    """Start engine + HTTP server in a non-daemon background thread, wait for
    the port to bind, then open the pywebview/WebView2 window. Non-daemon so
    closing the window does NOT kill the engine — user quits via tray."""
    import lavrentiy

    def _engine_target():
        lavrentiy.start_engine(run_http_server=True, block=True)

    threading.Thread(target=_engine_target, name="lavrentiy-engine",
                     daemon=False).start()

    if not _wait_for_port(DASHBOARD_PORT, timeout_s=60):
        # Engine never came up — surface to the user rather than opening a
        # blank window.
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "Lavrentiy engine failed to start. Check engine_err.log.",
                "Lavrentiy", 0x10)
        except Exception:
            pass
        sys.exit(1)

    import webview
    webview.create_window(
        title='Lavrentiy',
        url=DASHBOARD_URL,
        width=1280,
        height=820,
        resizable=True,
        confirm_close=False,
        js_api=_JSAPI(),
    )
    webview.start(gui='edgechromium')


def main():
    bundle = _bundle_dir()
    sys.path.insert(0, bundle)
    os.chdir(bundle)

    if '--native' in sys.argv or os.environ.get("LAV_NATIVE", "0") == "1":
        _run_native_window()
        return

    if os.environ.get("LAV_NO_BROWSER", "0") != "1":
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    import lavrentiy
    lavrentiy.start_engine(run_http_server=True, block=True)


if __name__ == "__main__":
    main()
