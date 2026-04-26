"""Re-exports the engine in lavrentiy.py."""
import os as _os
import sys as _sys
import importlib.util as _u

# DEBUG: prove __init__.py ran
try:
    with open(_os.path.join(_os.environ.get("TEMP", "."), "lavrentiy_init_TOP.log"), "a") as _f:
        _f.write(f"pid={_os.getpid()} __file__={__file__} _MEIPASS={getattr(_sys, '_MEIPASS', 'NONE')} frozen={getattr(_sys, 'frozen', False)}\n")
except Exception as _e:
    pass

# Find lavrentiy.py:
#   1. Bundled (PyInstaller --onefile): sys._MEIPASS is the unpack dir, and
#      lavrentiy.py was added via --add-data at the root.
#   2. Source: walk up one dir from this package's __init__.py to the repo
#      root where lavrentiy.py lives.
if hasattr(_sys, "_MEIPASS"):
    _engine_path = _os.path.join(_sys._MEIPASS, "lavrentiy.py")
elif getattr(_sys, "frozen", False):
    # Frozen but no _MEIPASS attr — shouldn't happen with PyInstaller, but
    # fall back to scanning sys.path for lavrentiy.py.
    _engine_path = None
    for _p in _sys.path:
        _candidate = _os.path.join(_p, "lavrentiy.py")
        if _os.path.exists(_candidate):
            _engine_path = _candidate
            break
    if _engine_path is None:
        # Last-ditch: dirname of executable + lavrentiy.py
        _engine_path = _os.path.join(_os.path.dirname(_sys.executable), "lavrentiy.py")
else:
    _engine_path = _os.path.normpath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lavrentiy.py")
    )

# Debug: write what was attempted, in case path is still wrong.
try:
    _dbg_log = _os.path.join(_os.environ.get("TEMP", "."), "lavrentiy_init_debug.log")
    with open(_dbg_log, "a", encoding="utf-8") as _f:
        _f.write(f"--- {_os.getpid()} ---\n")
        _f.write(f"frozen={getattr(_sys, 'frozen', False)}\n")
        _f.write(f"_MEIPASS={getattr(_sys, '_MEIPASS', '<unset>')}\n")
        _f.write(f"__file__={__file__}\n")
        _f.write(f"executable={_sys.executable}\n")
        _f.write(f"cwd={_os.getcwd()}\n")
        _f.write(f"sys.path[:5]={_sys.path[:5]}\n")
        _f.write(f"_engine_path={_engine_path}\n")
        _f.write(f"exists={_os.path.exists(_engine_path) if _engine_path else False}\n\n")
except Exception:
    pass

if "_lavrentiy_engine" not in _sys.modules:
    _spec = _u.spec_from_file_location("_lavrentiy_engine", _engine_path)
    _engine = _u.module_from_spec(_spec)
    _sys.modules["_lavrentiy_engine"] = _engine
    _spec.loader.exec_module(_engine)
else:
    _engine = _sys.modules["_lavrentiy_engine"]

for _name in dir(_engine):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_engine, _name)
