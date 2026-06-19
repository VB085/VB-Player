; Inno Setup script for VB Player Windows installer
; Usage: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss

[Setup]
AppName=VB Player
AppVersion=0.6
AppPublisher=VB085
DefaultDirName={autopf}\VB Player
DefaultGroupName=VB Player
OutputDir=..\dist
OutputBaseFilename=VB_Player_Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayName=VB Player
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\VB Player\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VB Player"; Filename: "{app}\VB Player.exe"
Name: "{group}\Uninstall VB Player"; Filename: "{uninstallexe}"
Name: "{autodesktop}\VB Player"; Filename: "{app}\VB Player.exe"

[Run]
Filename: "{app}\VB Player.exe"; Description: "Launch VB Player"; Flags: nowait postinstall skipifsilent
