; Lavrentiy Evaluation Build — Inno Setup script
; Builds: Lavrentiy-Eval-Setup-v1.4.0.exe
;
; Wraps the same Python runtime + launchers as the main Lavrentiy install,
; BUT swaps the engine for the patched copy in eval-build/engine/.
;
; v1.4.0: Full-local L1-L3. Cloud leaks closed.
;   - L1 ASR: faster-whisper large-v3-turbo (real Whisper, full verbose JSON
;     per-segment confidence — block detection, multi-temp voting, paralinguistic,
;     prosodic analysis all re-activate). Bundled as ~1.6 GB model.bin + metadata.
;     Moonshine + Vosk kept as layered fallbacks.
;   - L2/L3 reconstruction: Llama 3.2 3B Instruct Q4_K_M. Bundled as Ollama
;     blobs (~2 GB).
;   - L2/L3 Falcon validation: runs on local Llama. No cloud call. Previously
;     falcon_validate() always hit GPT-4o regardless of layer — that leak is closed.
;   - System prompt hardening + stop tokens + post-processing strip markdown,
;     preambles, emojis from local LLM output before paste target.
;
; v1.3.0 (previous): Fast cold-start — HTTP server binds :7878 in ~1s via a stub
;   handler that reports live boot_stage while heavy imports load in the main
;   thread. Stub swaps to the real DashboardHandler once init completes.
;
; v1.2.1 (previous): 8 stability fixes on the Current build
;   1. Command Mode tuple-unpack bug (engine/lavrentiy.py line ~6255)
;   2. reconstruct() bails cleanly if no OpenAI key
;   3. falcon_validate() bails cleanly if no OpenAI key
;   4. Startup console message when API key is missing
;   5. L1 hyphenated-stutter regex (catches w-w-want, s-schedule, m-m-meeting)
;   6. L1 word-repetition threshold lowered to 2+ (catches "to to", "the the")
;   7. Falcon L4 sees hard onsets + triggers (catch NEW avoidance substitutions)
;   8. Falcon L4 sees covert_profile.avoidance_pairs (ACCEPT reconstructions that
;      reverse tracked avoidance — don't flag them as phonetic hallucinations)
;
; Installs as "Lavrentiy Evaluation" in Program Files\Lavrentiy-Eval, so it
; lives SIDE-BY-SIDE with the Current install without clobbering it.
; Installer size: ~5 GB (engine + Python runtime + 3 bundled AI models).

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
SetupIconFile=C:\Users\georg\AppData\Local\Programs\Lavrentiy\engine\lavrentiy.ico
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
; 1) Pull launchers + bundled Python from the live install dir, SKIP its engine
Source: "C:\Users\georg\AppData\Local\Programs\Lavrentiy\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "engine\*,unins000.exe,unins000.dat,lav_err.txt,lav_out.txt,lavrentiy.pid,*\__pycache__\*"

; 2) Pull the patched engine from the repo's eval-build dir
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\engine\*"; DestDir: "{app}\engine"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "*\__pycache__\*,lav_err.txt,lav_out.txt,lavrentiy.pid,_backup_pre_fw_swap\*"

; 3) Bundle the faster-whisper large-v3-turbo model next to the engine so
;    local/fw_local.py finds it at <engine>/models/faster-whisper/<size>/.
;    ~1.6 GB. Required for L1 ASR to hit the new primary path.
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\models\faster-whisper\large-v3-turbo\*"; \
  DestDir: "{app}\engine\models\faster-whisper\large-v3-turbo"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; 4) Bundle Llama 3.2 3B into the user's Ollama cache so the engine can
;    call it immediately without a post-install "ollama pull" step.
;    ~2 GB. Blobs are content-addressed, so if the user already has them,
;    Inno Setup's ignoreversion flag is a no-op.
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\ollama-bundle\blobs\*"; \
  DestDir: "{userprofile}\.ollama\models\blobs"; \
  Flags: ignoreversion recursesubdirs
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\ollama-bundle\manifests\registry.ollama.ai\library\llama3.2\*"; \
  DestDir: "{userprofile}\.ollama\models\manifests\registry.ollama.ai\library\llama3.2"; \
  Flags: ignoreversion

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
