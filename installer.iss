; Inno Setup script for VB Player
; Download Inno Setup: https://jrsoftware.org/isdl.php (free)
; Build: iscc installer.iss

#define MyAppName "VB Player"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "VB Player Team"
#define MyAppURL "https://github.com/VB085/VB-Player"
#define MyAppExeName "VB Player.exe"

[Setup]
AppId={{7C3AED00-0000-0000-0000-000000000000}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=.
OutputBaseFilename=VB-Player-{#MyAppVersion}-setup
; SetupIconFile=assets\vb-player.png  ; need .ico, PNG not supported
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "out\VB Player\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
