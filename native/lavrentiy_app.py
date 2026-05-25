import sys
import json
import os
import datetime
import traceback
import faulthandler

# === Chromium sandbox workaround for PyInstaller --windowed bundles ===
# Chromium's helper process (QtWebEngineProcess.exe) crash-loops when its sandbox
# tries to initialize from inside _MEIPASS (strict ACLs + deep path nesting).
# Disabling the sandbox stops the loop. Must be set BEFORE QApplication is
# created — putting it here at the very top of the entry script guarantees that.
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
if getattr(sys, "frozen", False):
    _helper = os.path.join(sys._MEIPASS, "PySide6", "QtWebEngineProcess.exe")
    if os.path.exists(_helper):
        os.environ.setdefault("QTWEBENGINEPROCESS_PATH", _helper)

def _p(msg):
    """Step-by-step instrumentation — prints to console AND log file."""
    line = "[" + datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3] + "] " + msg
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

_LOG_PATH = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                         "lavrentiy_native_crash.log")

# Reset the log at start of run AND redirect stdout/stderr to it (windowed build
# has no console, so any stray print/Qt warning would be lost otherwise).
try:
    with open(_LOG_PATH, "w", encoding="utf-8") as f:
        f.write("=== RUN " + datetime.datetime.now().isoformat() + " ===\n")
    _log_stream = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_stream
    sys.stderr = _log_stream
except Exception:
    pass

_p("step 0: process started, PID=" + str(os.getpid()))

from pathlib import Path
_p("step 1: pathlib imported")

def _crash_logger(exc_type, exc_value, exc_tb):
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n=== CRASH " + datetime.datetime.now().isoformat() + " ===\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    print("=== CRASH ===", flush=True)
    traceback.print_exception(exc_type, exc_value, exc_tb)
    try:
        import ctypes
        msg = str(exc_value)[:300] + "\n\nFull traceback at:\n" + _LOG_PATH
        ctypes.windll.user32.MessageBoxW(0, msg, "Lavrentiy crashed", 0x10)
    except Exception:
        pass

sys.excepthook = _crash_logger
_p("step 2: excepthook installed")

try:
    _fh = open(_LOG_PATH, "a", encoding="utf-8")
    faulthandler.enable(file=_fh, all_threads=True)
    _p("step 3: faulthandler enabled")
except Exception as e:
    _p("step 3: faulthandler FAILED: " + repr(e))

_p("step 4: importing PySide6 modules...")
try:
    from PySide6.QtCore import QObject, Slot, QUrl
    _p("  - QtCore OK")
    from PySide6.QtWidgets import QApplication, QMainWindow
    _p("  - QtWidgets OK")
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _p("  - QtWebEngineWidgets OK")
    from PySide6.QtWebChannel import QWebChannel
    _p("  - QtWebChannel OK")
except Exception:
    _crash_logger(*sys.exc_info())
    raise

if hasattr(sys, "_MEIPASS"):
    REPO = Path(sys._MEIPASS)
    _p("step 5: bundled mode, REPO=" + str(REPO))
else:
    REPO = Path(__file__).resolve().parent.parent
    _p("step 5: dev mode, REPO=" + str(REPO))
sys.path.insert(0, str(REPO))

_p("step 6: importing lavrentiy.py via importlib...")
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location('lavrentiy', str(REPO / 'lavrentiy.py'))
    lavrentiy = importlib.util.module_from_spec(spec)
    sys.modules['lavrentiy'] = lavrentiy
    spec.loader.exec_module(lavrentiy)
    _p("step 6: lavrentiy module loaded")
except Exception:
    _crash_logger(*sys.exc_info())
    raise

class Bridge(QObject):
    @Slot(str, str, result=str)
    def api(self, path: str, body_json: str) -> str:
        body = json.loads(body_json) if body_json else {}
        return json.dumps(lavrentiy.dispatch_api(path, body))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        _p("  MainWindow.__init__ start")
        self.setWindowTitle("Lavrentiy")
        self.resize(1280, 820)
        _p("  creating QWebEngineView...")
        self.view = QWebEngineView()
        _p("  QWebEngineView created")
        self.bridge = Bridge()
        channel = QWebChannel()
        channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(channel)
        url = QUrl.fromLocalFile(str(REPO / "dashboard.html"))
        _p("  loading URL: " + url.toString())
        self.view.load(url)
        self.setCentralWidget(self.view)
        _p("  MainWindow.__init__ done")

def main():
    _p("step 7: creating QApplication")
    # Fix for QWebEngineView flicker (crash loop) in PyInstaller bundled mode
    if hasattr(sys, "_MEIPASS"):
        os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    app = QApplication(sys.argv)
    _p("step 8: QApplication created")
    _p("step 9: calling lavrentiy.start_engine(run_http_server=False, block=False)")
    try:
        lavrentiy.start_engine(run_http_server=False, block=False)
        _p("step 10: start_engine returned")
    except Exception:
        _p("step 10: start_engine THREW")
        _crash_logger(*sys.exc_info())
        raise
    _p("step 11: creating MainWindow")
    win = MainWindow()
    _p("step 12: showing window")
    win.show()
    _p("step 13: entering Qt event loop -- app should be visible NOW")
    rc = app.exec()
    _p("step 14: event loop exited with code " + str(rc))
    return rc

if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:
        _crash_logger(*sys.exc_info())
        rc = 99
    _p("=== Exit code: " + str(rc) + " ===")
    sys.exit(rc)
