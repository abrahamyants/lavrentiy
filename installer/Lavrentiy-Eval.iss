; Lavrentiy Evaluation Build — Inno Setup script
; Builds: Lavrentiy-Eval-Setup-v1.3.0.exe
;
; Wraps the same Python runtime + launchers as the main Lavrentiy install,
; BUT swaps the engine for the patched copy in eval-build/engine/.
;
; v1.3.0 adds fast cold-start: HTTP server binds :7878 in ~1s via a stub
; handler that reports live boot_stage while heavy imports load in the
; main thread. Stub swaps to the real DashboardHandler once init completes.
; Measured: ~9s from launch to fully ready (was ~30s).
;
; v1.2.1 fixes (8 total, vs the Current build):
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

[Setup]
AppName=Lavrentiy Evaluation
AppVersion=1.3.0
AppVerName=Lavrentiy Evaluation 1.3.0
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
OutputBaseFilename=Lavrentiy-Eval-Setup-v1.3.0
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
  Excludes: "*\__pycache__\*,lav_err.txt,lav_out.txt,lavrentiy.pid"

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
