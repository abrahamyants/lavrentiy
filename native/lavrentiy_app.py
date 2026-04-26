import sys, json
from pathlib import Path
from PySide6.QtCore import QObject, Slot, QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

# When bundled with PyInstaller --onefile, __file__ for the entry script is
# `<_MEIPASS>/lavrentiy_app.py` (PyInstaller strips the `native/` subdir),
# so parent.parent overreaches to Temp. Use _MEIPASS directly when frozen.
if hasattr(sys, "_MEIPASS"):
    REPO = Path(sys._MEIPASS)
else:
    REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import importlib.util
spec = importlib.util.spec_from_file_location('lavrentiy', str(REPO / 'lavrentiy.py'))
lavrentiy = importlib.util.module_from_spec(spec)
sys.modules['lavrentiy'] = lavrentiy
spec.loader.exec_module(lavrentiy)

class Bridge(QObject):
    @Slot(str, str, result=str)
    def api(self, path: str, body_json: str) -> str:
        body = json.loads(body_json) if body_json else {}
        return json.dumps(lavrentiy.dispatch_api(path, body))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lavrentiy")
        self.resize(1280, 820)
        self.view = QWebEngineView()
        self.bridge = Bridge()
        channel = QWebChannel()
        channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(channel)
        self.view.load(QUrl.fromLocalFile(str(REPO / "dashboard.html")))
        self.setCentralWidget(self.view)

def main():
    app = QApplication(sys.argv)
    lavrentiy.start_engine(run_http_server=False, block=False)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
