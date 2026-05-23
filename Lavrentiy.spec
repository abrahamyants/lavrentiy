# PyInstaller spec — Lavrentiy native app (PySide6 QWebEngineView, no browser)
#
# Mirrors Lavrentiy-onedir.spec for module/data coverage, but targets the
# native entry point and adds PySide6 + QtWebEngine support.

from PyInstaller.utils.hooks import collect_all
from pathlib import Path

REPO = Path(r'C:\Users\georg\Documents\GitHub\lavrentiy')

datas = [
    (str(REPO / 'lavrentiy.py'),       '.'),
    (str(REPO / 'l1_pack.py'),         '.'),
    (str(REPO / 'domain_pack.py'),     '.'),
    (str(REPO / 'rejection_store.py'), '.'),
    (str(REPO / 'style_examples.py'),  '.'),
    # H-4 unified prompt builder lives at wim/api/prompt_builder.py and is
    # imported by lavrentiy.py via a runtime sys.path.append("wim/api").
    # PyInstaller can't follow runtime path tricks — bundle it explicitly.
    (str(REPO / 'wim' / 'api' / 'prompt_builder.py'), '.'),
    (str(REPO / 'dashboard.html'),         '.'),
    (str(REPO / 'firebase-app-compat.js'), '.'),
    (str(REPO / 'firebase-auth-compat.js'),'.'),
    (str(REPO / 'silero_vad.onnx'),    '.'),
    (str(REPO / 'lavrentiy.ico'),      '.'),
    (str(REPO / 'api_key.txt'),        '.'),
    (str(REPO / 'anthropic_key.txt'),  '.'),
    (str(REPO / 'l1_packs'),           'l1_packs'),
    (str(REPO / 'lang_packs'),         'lang_packs'),
    (str(REPO / 'local'),              'local'),
]

# Optional dirs/files — include only if present (some live in onedir spec only)
_optional_datas = [
    (REPO / 'domain_packs', 'domain_packs'),
    (REPO / 'onboard.html',     '.'),
    (REPO / 'auth_google.html', '.'),
    (REPO / 'mobile.html',      '.'),
    (REPO / 'manifest.json',    '.'),
    (REPO / 'sw.js',            '.'),
]
for src, dst in _optional_datas:
    if src.exists():
        datas.append((str(src), dst))

binaries = []
hiddenimports = [
    'l1_pack', 'domain_pack', 'rejection_store', 'style_examples',
    'prompt_builder',
    'local', 'local.asr_local', 'local.fw_local', 'local.llm_local',
    'lavrentiy',
    'scipy.signal',
    'pyperclip',
    'pyautogui',
    'metaphone',
]

for pkg in (
    'PySide6',
    'faster_whisper', 'ctranslate2', 'onnxruntime',
    'sounddevice', 'soundfile', 'keyboard',
    'openai', 'anthropic', 'metaphone', 'pyperclip', 'pyautogui',
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(REPO / 'native' / 'lavrentiy_app.py')],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # GUI toolkits we don't use
        'PyQt5', 'PyQt6',
        'tkinter', 'matplotlib',
        # Notebook/dev tooling
        'IPython', 'jupyter', 'notebook',
        # Heavy ML deps pulled transitively but never called at runtime
        # (~470 MB combined — same trim as onedir spec)
        'torch', 'torchvision', 'torchaudio',
        'transformers',
        'numba',
        'pyarrow',
        'pandas',
        'sklearn',
        'tensorflow',
        'cv2',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Lavrentiy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(REPO / 'lavrentiy.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Lavrentiy',
)
