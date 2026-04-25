; Lavrentiy Evaluation Build — Inno Setup script
; Builds: Lavrentiy-Eval-Setup-v1.4.0.exe
;
; v1.4.0 (TRULY-LOCAL L1):
;   - L1 ASR (Transcribe): Moonshine BASE-en (Useful Sensors, ONNX). Fully on
;     device, runs without internet. Model files (~236 MB total: encoder 77 MB
;     + decoder 159 MB) are BUNDLED into the installer and installed into
;     {userprofile}\.cache\moonshine\base\ so first launch works offline.
;   - L2 / L3 (Reconstruct, Profile): cloud GPT-4o + cross-vendor Anthropic
;     Haiku 4.5 Falcon validation. Requires internet. Falls back to raw text
;     if offline.
;   - L4 (Disfluency clinical): cloud whisper-1 verbose_json + Anthropic Sonnet
;     4.6 with extended thinking + cloud GPT-4o cross-vendor Falcon. Requires
;     internet. Falls back to raw text if offline.
;
;   Net result: open the app, hit F9, dictate — L1 always works. L2-L4 require
;   internet but degrade gracefully when it's not there.
;
; Engine source: repo root C:\Users\georg\Documents\GitHub\lavrentiy\ — single
; source of truth (per CLAUDE.md). The eval-build\engine\ dir is no longer
; used as a separate frozen snapshot.
;
; Launchers + bundled Python: pulled from the live install dir at
; %LOCALAPPDATA%\Programs\Lavrentiy-Eval\, minus the engine + transient files.
;
; Installer size: ~600 MB (engine + Python runtime + Moonshine model). Down
; from the v1.3.0 plan that bundled faster-whisper (1.6 GB) and Llama Ollama
; blobs (2 GB) — both reverted in the 2026-04-24 evening pivot back to cloud
; L2-L4.
;
; --- Previous releases ---
; v1.3.0: Fast cold-start — HTTP server binds :7878 in ~1s via a stub handler
;   that reports live boot_stage while heavy imports load in main thread.
;   Stub swaps to the real DashboardHandler once init completes.
; v1.2.1: 8 stability fixes on the v1.0 baseline.

[Setup]
AppName=Lavrentiy Evaluation
AppVersion=1.4.0
AppVerName=Lavrentiy Evaluation 1.4.0
AppPublisher=Gurgen Abrahamyants
AppPublisherURL=https://github.com/gugosf114/lavrentiy
AppSupportURL=https://github.com/gugosf114/lavrentiy/issues
AppUpdatesURL=https://github.com/gugosf114/lavrentiy/releases
DefaultDirName={autopf}\Lavrentiy-Eval
DefaultGroupName=Lavrentiy Evaluation
UninstallDisplayIcon={app}\engine\lavrentiy.ico
UninstallDisplayName=Lavrentiy Evaluation
Compression=lzma2/max
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=Lavrentiy-Eval-Setup-v1.4.0
SetupIconFile=C:\Users\georg\AppData\Local\Programs\Lavrentiy-Eval\engine\lavrentiy.ico
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
DisableProgramGroupPage=yes
DisableReadyPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; 1) Pull launchers + bundled Python from the live Lavrentiy-Eval install,
;    SKIP the engine dir (we bundle a fresh engine from repo below) and any
;    transient runtime files (logs, pid, caches, prior backup snapshots).
Source: "C:\Users\georg\AppData\Local\Programs\Lavrentiy-Eval\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "engine\*,engine.bak.*\*,unins000.exe,unins000.dat,lav_err.txt,lav_out.txt,lavrentiy.pid,*\__pycache__\*,*.log"

; 2) Engine: pull from REPO ROOT — current source of truth.
;    Explicitly listed file-by-file rather than recursesubdirs so we don't
;    accidentally ship .git, tests, eval-build, installer, README, CLAUDE.md,
;    or any *_key.txt / *.pid / log files.
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\lavrentiy.py";    DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\dashboard.html";  DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\desktop.py";      DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\lavrentiy.ico";   DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\silero_vad.onnx"; DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\auth_google.html"; DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\onboard.html";    DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\manifest.json";   DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\sw.js";           DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\mobile.html";     DestDir: "{app}\engine"; Flags: ignoreversion

; 3) Local-pipeline modules. Excludes any *_key.txt files defensively.
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\local\*.py"; DestDir: "{app}\engine\local"; \
  Flags: ignoreversion; \
  Excludes: "*\__pycache__\*"

; 4) BUNDLED MOONSHINE MODEL (~236 MB) — what makes L1 work offline.
;    Engine code at local/whisper_local.py looks for these files at
;    {userprofile}\.cache\moonshine\base\. With ignoreversion, if the user
;    already has them (existing install / prior download), Inno Setup is a
;    no-op. Fresh-machine first launch: files already on disk, no internet
;    needed for L1.
Source: "C:\Users\georg\.cache\moonshine\base\encoder_model.onnx";        DestDir: "{%USERPROFILE}\.cache\moonshine\base"; Flags: ignoreversion
Source: "C:\Users\georg\.cache\moonshine\base\decoder_model_merged.onnx"; DestDir: "{%USERPROFILE}\.cache\moonshine\base"; Flags: ignoreversion

[Icons]
Name: "{group}\Lavrentiy Evaluation"; Filename: "{app}\Lavrentiy.vbs"; IconFilename: "{app}\engine\lavrentiy.ico"; Comment: "Voice reconstruction engine (evaluation build)"
Name: "{group}\Uninstall Lavrentiy Evaluation"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Lavrentiy Evaluation"; Filename: "{app}\Lavrentiy.vbs"; IconFilename: "{app}\engine\lavrentiy.ico"; Comment: "Voice reconstruction engine (evaluation build)"; Tasks: desktopicon

[Run]
Filename: "{app}\Lavrentiy.vbs"; Description: "Launch Lavrentiy Evaluation now"; Flags: nowait shellexec postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\lav_err.txt"
Type: files; Name: "{app}\lav_out.txt"
Type: files; Name: "{app}\engine\lavrentiy.pid"
Type: filesandordirs; Name: "{app}\engine\__pycache__"
Type: filesandordirs; Name: "{app}\engine\local\__pycache__"
