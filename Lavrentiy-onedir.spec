# Lavrentiy-onedir.spec — PyInstaller --onedir build (drift-proof bundling).
#
# WHY --onedir AND NOT --onefile:
#   Failure log #78 (2026-04-26): --onefile cold-launch is 30-60s on every run
#   because the bootloader re-extracts the ~700 MB bundle to %TEMP% each time.
#   --onedir extracts once at build time and launches in 1-3s thereafter.
#
# WHY THIS REPLACES THE INNO SETUP MANUAL FILE LIST:
#   The v1.5.7 Lavrentiy-Eval.iss broke because lavrentiy.py grew imports
#   (domain_pack, l1_pack, rejection_store, style_examples) that were never
#   added to the .iss [Files] block. PyInstaller walks the IMPORT GRAPH at
#   build time, so any sibling module imported by lavrentiy.py is auto-bundled.
#   Future imports added later? Auto-bundled on next build. No more drift.
#
# OUTPUT:
#   dist-onedir/Lavrentiy/
#     Lavrentiy.exe          <-- launcher entry, double-click to run
#     _internal/             <-- Python runtime + all libs + all data files
#       lavrentiy.py
#       l1_pack.py, domain_pack.py, rejection_store.py, style_examples.py
#       dashboard.html, onboard.html, auth_google.html
#       silero_vad.onnx, lavrentiy.ico
#       l1_packs/, domain_packs/, lang_packs/, local/
#       models/faster-whisper/small.en/   (offline L1)
#       <python runtime + every dep>
#
# DISTRIBUTION:
#   Wrap dist-onedir/Lavrentiy/ in a fresh Inno Setup script (Lavrentiy-onedir.iss)
#   that does NOT manually list files — just `Source: dist-onedir\Lavrentiy\*;
#   DestDir: {app}; Flags: recursesubdirs`. Single .exe download for the user
#   (the installer), CD-ROM model — install once, runs forever.

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
    (str(REPO / 'wim' / 'api' / 'learning_backend.py'), '.'),
    (str(REPO / 'wim' / 'api' / 'profile_terms.py'), '.'),
    (str(REPO / 'dashboard.html'),     '.'),
    (str(REPO / 'onboard.html'),       '.'),
    (str(REPO / 'auth_google.html'),   '.'),
    (str(REPO / 'manifest.json'),      '.'),
    (str(REPO / 'sw.js'),              '.'),
    (str(REPO / 'silero_vad.onnx'),    '.'),
    (str(REPO / 'lavrentiy.ico'),      '.'),
    (str(REPO / 'l1_packs'),           'l1_packs'),
    (str(REPO / 'domain_packs'),       'domain_packs'),
    (str(REPO / 'lang_packs'),         'lang_packs'),
    (str(REPO / 'local'),              'local'),
    (str(REPO / 'eval-build' / 'models' / 'faster-whisper' / 'small.en'),
     'models/faster-whisper/small.en'),
]

binaries = []
hiddenimports = [
    'l1_pack', 'domain_pack', 'rejection_store', 'style_examples',
    'prompt_builder', 'learning_backend', 'profile_terms',
    'local', 'local.asr_local', 'local.fw_local',
    'scipy.signal',
    'pyperclip',
    'pyautogui',
    'metaphone',
]

for pkg in (
    'faster_whisper', 'ctranslate2', 'onnxruntime',
    'sounddevice', 'soundfile', 'keyboard',
    'openai', 'anthropic', 'metaphone', 'pyperclip',
    'pyautogui',
    # Native app window (pywebview + WebView2 via pythonnet). This is the
    # v1.7.2 shortcut path; browser mode remains a troubleshooting fallback.
    'webview', 'pythonnet', 'clr_loader',
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(REPO / 'lavrentiy_launcher.py')],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6', 'PyQt5', 'PyQt6',
        'tkinter', 'matplotlib',
        'IPython', 'jupyter', 'notebook',
        # v1.6.1 trim — none of these are imported by lavrentiy.py or its sibling
        # modules. They were pulled in transitively via collect_all on ctranslate2 /
        # onnxruntime / faster_whisper. Stripping ~470 MB of dead weight.
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

# --onedir: launcher .exe ships separately from the binaries/data, both go in
# the same dist folder. exclude_binaries=True tells EXE not to embed everything
# in the .exe — they end up in _internal/ next to it via COLLECT.
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
