; Lavrentiy.iss — Inno Setup installer for v1.6.0+ (drift-proof bundling).
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
;        -> Produces installer\Output\Lavrentiy-Setup-v1.6.0.exe
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
AppVersion=1.6.8
AppVerName=Lavrentiy 1.6.8
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
OutputBaseFilename=Lavrentiy-Setup-v1.6.8
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

[Icons]
; v1.6.3 — two shortcuts, two ways to open the same dashboard:
;   Lavrentiy           -> Lavrentiy.vbs        (Chrome/Edge --app= borderless)
;   Lavrentiy (Native)  -> Lavrentiy-Native.vbs (pywebview/WebView2 native window)
; Both produce a chromeless window with the dashboard inside. Difference is the
; underlying rendering engine.
Name: "{group}\Lavrentiy";                Filename: "{app}\Lavrentiy.vbs";        IconFilename: "{app}\_internal\lavrentiy.ico"; Comment: "Voice reconstruction engine (Chrome/Edge window)"
Name: "{group}\Lavrentiy (Native)";       Filename: "{app}\Lavrentiy-Native.vbs"; IconFilename: "{app}\_internal\lavrentiy.ico"; Comment: "Voice reconstruction engine (native WebView2 window)"
Name: "{group}\Uninstall Lavrentiy";      Filename: "{uninstallexe}"
Name: "{autodesktop}\Lavrentiy";          Filename: "{app}\Lavrentiy.vbs";        IconFilename: "{app}\_internal\lavrentiy.ico"; Comment: "Voice reconstruction engine (Chrome/Edge window)"; Tasks: desktopicon
Name: "{autodesktop}\Lavrentiy (Native)"; Filename: "{app}\Lavrentiy-Native.vbs"; IconFilename: "{app}\_internal\lavrentiy.ico"; Comment: "Voice reconstruction engine (native WebView2 window)"; Tasks: desktopicon

[Run]
Filename: "{app}\Lavrentiy.vbs"; Description: "Launch Lavrentiy now"; Flags: nowait shellexec postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\_internal\engine_err.log"
Type: files; Name: "{app}\_internal\engine_out.log"
Type: files; Name: "{app}\_internal\engine_lifecycle.log"
Type: files; Name: "{app}\_internal\lavrentiy.pid"
Type: files; Name: "{app}\_internal\lav_err.txt"
Type: files; Name: "{app}\_internal\lav_out.txt"
