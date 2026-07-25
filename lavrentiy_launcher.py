"""Lavrentiy — launcher (PyInstaller --onedir entry point).

Two launch modes:
  * Default — start engine + HTTP server, let the .vbs wrapper open the
    dashboard in Edge/Chrome --app= chromeless mode (LAV_NO_BROWSER=1).
    Used by Lavrentiy.vbs.
  * --native — start engine + HTTP server, then open the dashboard in a
    pywebview/WebView2 native window. No external browser involved.
    Used by Lavrentiy-Native.vbs.

Self-contained: when frozen, all .py modules + data files (l1_packs/,
domain_packs/, lang_packs/, local/, dashboard.html, silero_vad.onnx, and the
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

    # MUST be "localhost", never "127.0.0.1". Google treats them as two
    # different origins, and only http://localhost:7878 is on the OAuth
    # client's authorized JavaScript origins list. Opening the 127.0.0.1
    # form makes Google Identity Services reject the sign-in with
    # "doesn't comply with Google's OAuth 2.0 policy" — which is what every
    # native-window user hit from v1.7.1 onward, because v1.7.1 made the
    # native shortcut the default and this is the only route that used the
    # 127.0.0.1 spelling. The engine (lavrentiy.py handle_POST_api_open_signin)
    # and dashboard.html fallbacks all use localhost; this was the one outlier.
    SIGNIN_URL = 'http://localhost:7878/auth/google'

    def open_google_signin(self):
        try:
            webbrowser.open(self.SIGNIN_URL, new=2)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}


def _native_log(msg):
    """Append a diagnostic line to native_boot.log next to the .exe. PyInstaller
    --windowed mode (which Lavrentiy.exe uses) silently discards stdout/stderr,
    so without this file every pywebview failure mode is invisible to the user."""
    try:
        log_path = os.path.join(_bundle_dir(), 'native_boot.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            f.flush()
    except Exception:
        pass  # logging itself must never crash the launcher


def _show_error_dialog(text, title='Lavrentiy'):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        pass


def _run_native_window():
    """Start engine + HTTP server in a non-daemon background thread, wait for
    the port to bind, then open the pywebview/WebView2 window. Non-daemon so
    closing the window does NOT kill the engine — user quits via tray.

    Logs every step to native_boot.log so silent failures are diagnosable."""
    _native_log("step 1: entered _run_native_window")
    _native_log(f"step 2: bundle_dir={_bundle_dir()} sys.executable={sys.executable}")
    _native_log(f"step 3: sys.argv={sys.argv}")

    try:
        import lavrentiy
        _native_log("step 4: lavrentiy module imported")
    except Exception as e:
        _native_log(f"FAIL at step 4: lavrentiy import failed: {type(e).__name__}: {e}")
        import traceback
        _native_log(traceback.format_exc()[:1500])
        _show_error_dialog(f"Failed to import Lavrentiy engine:\n{type(e).__name__}: {e}\n\nSee native_boot.log.")
        sys.exit(1)

    def _engine_target():
        try:
            lavrentiy.start_engine(run_http_server=True, block=True)
        except Exception as e:
            _native_log(f"engine thread crashed: {type(e).__name__}: {e}")

    threading.Thread(target=_engine_target, name="lavrentiy-engine",
                     daemon=False).start()
    _native_log("step 5: engine thread spawned (non-daemon)")

    if not _wait_for_port(DASHBOARD_PORT, timeout_s=60):
        _native_log("FAIL at step 6: engine never bound port 7878 within 60s")
        _show_error_dialog("Lavrentiy engine failed to start. Check engine_err.log and native_boot.log.")
        sys.exit(1)
    _native_log("step 6: port 7878 is bound (engine up)")

    try:
        import webview
        _native_log(f"step 7: webview module imported ({getattr(webview, '__file__', '?')})")
    except Exception as e:
        _native_log(f"FAIL at step 7: webview import failed: {type(e).__name__}: {e}")
        import traceback
        _native_log(traceback.format_exc()[:1500])
        _show_error_dialog(f"pywebview import failed in the bundle:\n{type(e).__name__}: {e}\n\nFalling back to default browser.")
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception:
            pass
        return  # engine keeps running, user gets browser instead

    try:
        webview.create_window(
            title='Lavrentiy',
            url=DASHBOARD_URL,
            width=1280,
            height=820,
            resizable=True,
            confirm_close=False,
            js_api=_JSAPI(),
        )
        _native_log("step 8: create_window returned")
    except Exception as e:
        _native_log(f"FAIL at step 8: create_window failed: {type(e).__name__}: {e}")
        import traceback
        _native_log(traceback.format_exc()[:1500])
        _show_error_dialog(f"pywebview.create_window failed:\n{type(e).__name__}: {e}")
        sys.exit(1)

    # Try backend chain. edgechromium is preferred (WebView2 Runtime ships with
    # Win10/11). mshtml is the legacy fallback (IE-based, always present).
    # None lets pywebview auto-pick the best available backend at runtime.
    for backend in ('edgechromium', 'mshtml', None):
        backend_name = backend or 'auto-detected'
        try:
            _native_log(f"step 9: attempting webview.start(gui={backend_name!r})")
            if backend is None:
                webview.start()
            else:
                webview.start(gui=backend)
            _native_log(f"step 10: webview.start returned cleanly with gui={backend_name}")
            return
        except Exception as e:
            _native_log(f"webview.start(gui={backend_name!r}) failed: {type(e).__name__}: {e}")
            import traceback
            _native_log(traceback.format_exc()[:1500])
            # Clean any partially-created windows before retrying with a different backend
            try:
                while webview.windows:
                    webview.windows[0].destroy()
            except Exception:
                pass

    # All backends exhausted. Fall back to opening in the user's default browser.
    _native_log("FAIL: all pywebview backends failed; falling back to default browser")
    _show_error_dialog("Native window backend unavailable. Opening dashboard in your default browser instead.")
    try:
        webbrowser.open(DASHBOARD_URL)
    except Exception:
        pass


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
