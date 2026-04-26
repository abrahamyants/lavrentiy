# PyInstaller spec — Lavrentiy native app
from PyInstaller.utils.hooks import collect_all

REPO = r'C:\Users\georg\Documents\GitHub\lavrentiy'

datas = [
    (REPO + r'\lavrentiy.py', '.'),
    (REPO + r'\dashboard.html', '.'),
    (REPO + r'\silero_vad.onnx', '.'),
    (REPO + r'\lavrentiy.ico', '.'),
    (REPO + r'\api_key.txt', '.'),
    (REPO + r'\anthropic_key.txt', '.'),
    (REPO + r'\l1_pack.py', '.'),
    (REPO + r'\lang_packs', 'lang_packs'),
    (REPO + r'\l1_packs', 'l1_packs'),
    (REPO + r'\local', 'local'),
]

binaries = []
hiddenimports = ['scipy.signal', 'pyperclip', 'pyautogui', 'lavrentiy']

for pkg in ('PySide6', 'moonshine_onnx', 'keyboard', 'soundfile',
            'sounddevice', 'onnxruntime', 'anthropic', 'openai'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [REPO + r'\native\lavrentiy_app.py'],
    pathex=[REPO],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[REPO + r'\lavrentiy.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Lavrentiy',
)
