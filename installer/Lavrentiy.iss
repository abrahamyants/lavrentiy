; Lavrentiy.iss — Inno Setup installer for v1.7.0 (drift-proof bundling).
;
; CONTRAST WITH v1.5.7 (Lavrentiy-Eval.iss):
;   v1.5.7 manually enumerated each engine source file in the [Files] block.
;   When lavrentiy.py grew imports (domain_pack, l1_pack, rejection_store,
;   style_examples) the .iss was never updated — fresh installs crashed at
;   import time with ModuleNotFoundError. This .iss takes the OPPOSITE
;   approach: it bundles whatever PyInstaller's --onedir build produced.
;   PyInstaller walks the import graph, so any module imported by lavrentiy.py
;   is auto-included. New imports added later? Auto-included on next build.
;   No human in the loop, no drift.
;
; BUILD SEQUENCE:
;   1. py -3 -m PyInstaller Lavrentiy-onedir.spec --noconfirm \
;        --distpath dist-onedir --workpath build-onedir
;        -> Produces dist-onedir\Lavrentiy\Lavrentiy.exe + _internal\
;   2. iscc installer\Lavrentiy.iss
;        -> Produces installer\Output\Lavrentiy-Setup-v1.7.0.exe
;
; INSTALL TARGET:
;   {userpf}\Lavrentiy = %LOCALAPPDATA%\Programs\Lavrentiy
;   Per-user install. No admin elevation. No Program Files. Writable for
;   engine logs (engine_err.log, engine_lifecycle.log, lav_err.txt) which
;   live next to lavrentiy.py inside _internal\.
;
; NEW APPID:
;   v1.5.7 layout was {app}\engine\lavrentiy.py. v1.6.0 layout is
;   {app}\Lavrentiy.exe + {app}\_internal\. These are incompatible enough
;   that an in-place upgrade would scatter conflicting files. Fresh AppId
;   means installing v1.6.0 leaves any v1.5.7 install intact (fallback), and
;   uninstalling cleans only its own files. Migrate manually if desired.

[Setup]
AppId={{B7E5F4A2-9C3D-4E1B-8A6F-2D8B5E9C1F3A}}
AppName=Lavrentiy
AppVersion=1.7.0
AppVerName=Lavrentiy 1.7.0
AppPublisher=Gurgen Abrahamyants
AppPublisherURL=https://github.com/gugosf114/lavrentiy
AppSupportURL=https://github.com/gugosf114/lavrentiy/issues
AppUpdatesURL=https://github.com/gugosf114/lavrentiy/releases
DefaultDirName={userpf}\Lavrentiy
DefaultGroupName=Lavrentiy
UninstallDisplayIcon={app}\_internal\lavrentiy.ico
UninstallDisplayName=Lavrentiy
Compression=lzma2/max
SolidCompression=yes
OutputDir=C:\Users\georg\Documents\GitHub\lavrentiy\installer\Output
OutputBaseFilename=Lavrentiy-Setup-v1.7.0
SetupIconFile=C:\Users\georg\Documents\GitHub\lavrentiy\lavrentiy.ico
PrivilegesRequired=lowest
WizardStyle=modern
DisableProgramGroupPage=yes
DisableReadyPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Force-close any running Lavrentiy.exe before installing so files aren't locked.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; PyInstaller --onedir build, plus both launcher .vbs files next to the .exe.
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\dist-onedir\Lavrentiy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\Lavrentiy.vbs";         DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Users\georg\Documents\GitHub\lavrentiy\Lavrentiy-Native.vbs";  DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; v1.6.8 and earlier accidentally shipped developer API keys beside the frozen
; engine. Remove every historical app-directory location during upgrade.
; User-entered keys in v1.7.0 live under %USERPROFILE%\.lavrentiy instead.
Type: files; Name: "{app}\_internal\api_key.txt"
Type: files; Name: "{app}\_internal\anthropic_key.txt"
Type: files; Name: "{app}\api_key.txt"
Type: files; Name: "{app}\anthropic_key.txt"
Type: files; Name: "{app}\engine\api_key.txt"
Type: files; Name: "{app}\engine\anthropic_key.txt"

[Icons]
; V1 presents one normal application shortcut. The browser-mode launcher stays
; installed as a troubleshooting fallback but is not pushed onto the user.
Name: "{group}\Lavrentiy";                Filename: "{app}\Lavrentiy-Native.vbs"; IconFilename: "{app}\_internal\lavrentiy.ico"; Comment: "Voice-to-intent for Windows"
Name: "{group}\Uninstall Lavrentiy";      Filename: "{uninstallexe}"
Name: "{autodesktop}\Lavrentiy";          Filename: "{app}\Lavrentiy-Native.vbs"; IconFilename: "{app}\_internal\lavrentiy.ico"; Comment: "Voice-to-intent for Windows"; Tasks: desktopicon

[Run]
Filename: "{app}\Lavrentiy-Native.vbs"; Description: "Launch Lavrentiy now"; Flags: nowait shellexec postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\_internal\engine_err.log"
Type: files; Name: "{app}\_internal\engine_out.log"
Type: files; Name: "{app}\_internal\engine_lifecycle.log"
Type: files; Name: "{app}\_internal\lavrentiy.pid"
Type: files; Name: "{app}\_internal\lav_err.txt"
Type: files; Name: "{app}\_internal\lav_out.txt"
