; Lavrentiy Inno Setup script
; Builds: Lavrentiy-Setup-v1.2.0.exe
; Wraps: C:\Users\georg\AppData\Local\Programs\Lavrentiy\ (installed copy)
; Runs via: Lavrentiy.vbs (no pywebview, uses Edge --app)

[Setup]
AppName=Lavrentiy
AppVersion=1.2.0
AppVerName=Lavrentiy 1.2.0
AppPublisher=Gurgen Abrahamyants
AppPublisherURL=https://github.com/gugosf114/lavrentiy
AppSupportURL=https://github.com/gugosf114/lavrentiy/issues
AppUpdatesURL=https://github.com/gugosf114/lavrentiy/releases
DefaultDirName={autopf}\Lavrentiy
DefaultGroupName=Lavrentiy
UninstallDisplayIcon={app}\engine\lavrentiy.ico
UninstallDisplayName=Lavrentiy
Compression=lzma2/max
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=Lavrentiy-Setup-v1.2.0
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
; Source everything from portable/, exclude secrets + runtime logs + pycache
Source: "C:\Users\georg\AppData\Local\Programs\Lavrentiy\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "engine\api_key.txt,engine\gemini_api_key.txt,lav_err.txt,lav_out.txt,*\__pycache__\*,lavrentiy.pid"

[Icons]
Name: "{group}\Lavrentiy"; Filename: "{app}\Lavrentiy.vbs"; IconFilename: "{app}\engine\lavrentiy.ico"; Comment: "Voice reconstruction engine"
Name: "{group}\Uninstall Lavrentiy"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Lavrentiy"; Filename: "{app}\Lavrentiy.vbs"; IconFilename: "{app}\engine\lavrentiy.ico"; Comment: "Voice reconstruction engine"; Tasks: desktopicon

[Run]
Filename: "{app}\Lavrentiy.vbs"; Description: "Launch Lavrentiy now"; Flags: nowait shellexec postinstall skipifsilent

[UninstallDelete]
; Clean up any files the engine creates during use (logs, cache)
Type: files; Name: "{app}\lav_err.txt"
Type: files; Name: "{app}\lav_out.txt"
Type: files; Name: "{app}\engine\lavrentiy.pid"
Type: filesandordirs; Name: "{app}\engine\__pycache__"
