; Lavrentiy Evaluation Build — Inno Setup script
; Builds: Lavrentiy-Eval-Setup-v1.5.7.exe
;
; v1.5.7 (DASHBOARD UI FORWARD-PORT — 2026-05-01):
;   - Dedicated L1 SOURCE section reinstated between PATIENCE and WHISPER
;     in the sidebar (matching the c0acb93 commit's design). Previous
;     L1 row inside the Whisper card was removed.
;   - EQ "ears" markup forward-ported: outer + inner column on each side
;     of the bezel knob. CSS now includes .eq-near positioning + the
;     eq-rest @keyframes traveling-wave animation.
;   - Console legend box restyled to floating-corner look: thin tan-gold
;     border at 35% opacity, rounded corners, semi-transparent red
;     gradient fill, 12px from bottom-right.
;
; v1.5.6 (HIDDEN-WINDOW FIX + L1 SOURCE TOGGLE — 2026-04-30):
;   - desktop.py boot() now calls win.show() on the splash window before
;     running engine startup. Without this, pywebview created the window
;     but Windows reported IsWindowVisible=False on some setups, making
;     the desktop shortcut click look dead.
;   - Dashboard sidebar Whisper card has a new "L1 source" row at the top.
;     Click to flip CLOUD ↔ LOCAL. CLOUD = OpenAI whisper-1 (multilingual,
;     internet). LOCAL = bundled faster-whisper small.en (English-only,
;     offline). Mirrors WiM Android's bubble-menu L1 SRC toggle.
;
; v1.5.5 (LANGUAGES STRIPPED — 2026-04-30):
;   - All multilingual UI removed. Dashboard is English-only.
;   - Language toggle row [EN][RU][ES][PT][FR] deleted from header.
;   - I18N object collapsed to en-only — 192 entries, no more ru/es/pt/fr
;     keys. The t() lookup function is preserved (returns en value), so
;     existing template code keeps working.
;   - Reason: French translations had a double-backslash apostrophe escape
;     bug ("n\\'est" instead of "n\'est") that crashed the JS parser with
;     "Unexpected identifier 'est'" and silently broke the entire I18N
;     object. Rather than re-escape and risk other rebuild bugs, all
;     non-English translations were ripped. WiM Android keeps its 5-lang
;     UI separately — only Lavrentiy is monolingual now.
;
; v1.5.4 (LAUNCHER MUTEX FIX — 2026-04-30):
;   - desktop.py mutex check used to silently sys.exit(0) when another
;     instance was already running. After the post-install auto-launch,
;     double-clicking the desktop shortcut hit that branch every time — the
;     icon felt dead. Now opens http://127.0.0.1:7878/ in the user's default
;     browser when the mutex is already taken, so the icon always shows UI.
;   - Same engine + dashboard + small.en + bundled keys as v1.5.3.
;
; v1.5.3 (BUNDLED API KEYS — 2026-04-30):
;   - OpenAI key (api_key.txt) and Anthropic key (anthropic_key.txt) bundled
;     into {app}\engine\. Wife / evaluator opens the app and dictates — zero
;     setup. No "paste your key" screen on first launch.
;   - SECURITY NOTE: anyone who gets this installer can see + use both keys.
;     Treat the .exe like a credential. Do not put on a public USB or
;     uploaded share. OpenAI charges + Anthropic charges accrue to George's
;     accounts on every L1-cloud / L2 / L3 / L4 call.
;
; v1.5.2 (CLEAN-INSTALL HYGIENE — 2026-04-30):
;   - Stable AppId added so future versions auto-uninstall this one before
;     placing new files. No more parallel zombie installs.
;   - PrepareToInstall [Code] hook kills any running Lavrentiy process
;     (filtered by command-line containing "Lavrentiy" — safe, never touches
;     unrelated pythonw.exe) and runs the legacy AppName-based uninstaller
;     silently if found. Combined with CloseApplications=force, the installer
;     can be double-clicked while the engine is running and Just Works.
;   - Same engine + dashboard + small.en bundle as v1.5.1. All 5 languages
;     ship (EN/RU/ES/PT/FR — 192 I18N entries).
;
; v1.5.1 (TWO-PEER L1 + FALCON RIPPED — 2026-04-30):
;   - L1 ASR is now a two-peer choice (parity with WiM Android):
;       Cloud: OpenAI whisper-1 API. Multilingual (EN/ES/RU/PT/FR/etc).
;       Local: faster-whisper small.en (~486 MB bundled). English-only.
;     User toggles via dashboard /api/l1_asr endpoint. Default = cloud.
;   - Moonshine + Vosk removed. local/whisper_local.py + local/vosk_local.py
;     deleted; local/asr_local.py rewritten to faster-whisper only.
;   - L2/L3 reconstruction: GPT-4o (cloud whisper-1 ASR + GPT-4o LLM).
;     Falcon cross-vendor validator REMOVED — operator decision: trust the
;     reconstructor without a second pass. ~$0.0008/session saved + ~400ms
;     latency saved per L2/L3 reconstruction.
;   - L4 reconstruction: Sonnet 4.6 with extended thinking (cloud whisper-1
;     verbose_json ASR + Sonnet 4.6 LLM). Falcon also removed — Sonnet's
;     reasoning trace IS the validator at this layer.
;   - Installer size ~600 MB (engine + Python sidecar + small.en). Up from
;     v1.4 Moonshine bundle (~600 MB total) but with multilingual cloud
;     parity AND English-only local that's actually accurate on disfluent
;     speech (small.en > Moonshine.en on heavy stutter).
;
; v1.5.0 (FIVE-LANGUAGE UI — 2026-04-30):
;   - Dashboard UI shipped in EN / RU / ES / PT / FR. All 192 I18N entries
;     translated. Top-right header has [EN] [RU] [ES] [PT] [FR] toggle.
;
; v1.4.0 (legacy — Moonshine BASE-en bundled at ~236 MB; replaced by v1.5.1
;   above): L1 = bundled Moonshine ONNX, L2/L3 = cloud GPT-4o + Haiku Falcon,
;   L4 = cloud whisper-1 + Sonnet 4.6 ext-think + GPT-4o Falcon.
;
;   Net result: open the app, hit F9, dictate — cloud L1 by default.
;   Offline-only users flip the toggle and accept a one-time HF download
;   for the local faster-whisper model.
;
; Engine source: repo root C:\Users\georg\Documents\GitHub\lavrentiy\ — single
; source of truth (per CLAUDE.md). The eval-build\engine\ dir is no longer
; used as a separate frozen snapshot.
;
; Launchers + bundled Python: pulled from the live install dir at
; %LOCALAPPDATA%\Programs\Lavrentiy-Eval\, minus the engine + transient files.
;
; Installer size: ~600 MB (engine + Python runtime + faster-whisper small.en
; model). Down from the v1.3.0 plan that bundled faster-whisper large-v3-turbo
; (1.6 GB) and Llama Ollama blobs (2 GB) — both reverted in the 2026-04-24
; evening pivot back to cloud L2-L4. Moonshine + Vosk fallbacks retired
; 2026-04-30 (see v1.5.1 entry above).
;
; --- Previous releases ---
; v1.3.0: Fast cold-start — HTTP server binds :7878 in ~1s via a stub handler
;   that reports live boot_stage while heavy imports load in main thread.
;   Stub swaps to the real DashboardHandler once init completes.
; v1.2.1: 8 stability fixes on the v1.0 baseline.

[Setup]
; Stable AppId — anchored 2026-04-30 v1.5.2. From here forward, Inno detects
; this GUID in the registry on install and auto-uninstalls the prior version
; (silently) before placing new files. Older v1.4–v1.5.1 installs pre-date
; this AppId, so the [Code] PrepareToInstall hook below also scans the legacy
; "Lavrentiy Evaluation_is1" uninstall key and runs it explicitly.
AppId={{8A4D2F1C-7B3E-4A91-B5C8-9F2E1D6A4B7C}}
AppName=Lavrentiy Evaluation
AppVersion=1.5.7
AppVerName=Lavrentiy Evaluation 1.5.7
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
OutputBaseFilename=Lavrentiy-Eval-Setup-v1.5.7
SetupIconFile=C:\Users\georg\AppData\Local\Programs\Lavrentiy-Eval\engine\lavrentiy.ico
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Force-close the running Lavrentiy if the user runs the installer while the
; engine is up. Combined with the [Code] PrepareToInstall hook below, this
; ensures no file-in-use locks block the install.
CloseApplications=force
RestartApplications=no
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
  Excludes: "engine\*,engine.bak.*\*,models\*,unins000.exe,unins000.dat,unins001.exe,unins001.dat,lav_err.txt,lav_out.txt,lavrentiy.pid,*\__pycache__\*,*.log"

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

; 4) BUNDLED FASTER-WHISPER SMALL.EN MODEL (~486 MB, English-only).
;    L1 ASR is a TWO-PEER CHOICE (not fallback chain), parity with WiM Android:
;      - Cloud: OpenAI whisper-1 API. Multilingual. Default for first launch.
;      - Local: faster-whisper small.en. English-only. Free, offline, privacy.
;    User toggles via POST /api/l1_asr {cloud: bool} from the dashboard.
;    Non-English locales must use the cloud path (small.en can't decode
;    Spanish/Russian/Portuguese/French phonemes).
;    Engine code at local/fw_local.py looks for model.bin at
;    {app}\models\faster-whisper\small.en\, so we drop it there directly.
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\models\faster-whisper\small.en\model.bin";        DestDir: "{app}\models\faster-whisper\small.en"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\models\faster-whisper\small.en\config.json";      DestDir: "{app}\models\faster-whisper\small.en"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\models\faster-whisper\small.en\tokenizer.json";   DestDir: "{app}\models\faster-whisper\small.en"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\models\faster-whisper\small.en\vocabulary.txt";   DestDir: "{app}\models\faster-whisper\small.en"; Flags: ignoreversion

; 5) BUNDLED API KEYS — zero-setup first launch.
;    Pulled from the live Lavrentiy-Eval install dir (the active keys George
;    is currently using). Engine reads these via lavrentiy.py:158 + :173.
;    See SECURITY NOTE in header — this installer carries credentials.
Source: "C:\Users\georg\AppData\Local\Programs\Lavrentiy-Eval\engine\api_key.txt";        DestDir: "{app}\engine"; Flags: ignoreversion
Source: "C:\Users\georg\AppData\Local\Programs\Lavrentiy-Eval\engine\anthropic_key.txt";  DestDir: "{app}\engine"; Flags: ignoreversion

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

; [Code] section was here in v1.5.2/1.5.3 — got removed because it crashed
; Inno at runtime (install rolled back at "Created temporary directory" step,
; before any file extraction). The intent was to taskkill running Lavrentiy
; processes and run the legacy uninstaller silently. Restored as a separate
; deferred task once the Pascal syntax is validated against a working sample.
;
; What this loses for now:
;   - If the user has the engine running while installing, install may fail
;     with "file in use" errors. Workaround: close the running app first.
;   - Legacy v1.4 / v1.5.0 / v1.5.1 installs need to be uninstalled manually
;     from Settings → Apps before installing v1.5.3 — the built-in AppId
;     auto-uninstall only catches future v1.5.3+ builds (AppId is new here).
;
; CloseApplications=force in [Setup] still tries to close running apps via
; the standard Windows Restart Manager, which catches most cases.
