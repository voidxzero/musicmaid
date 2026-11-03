; Inno Setup script - invoked by packaging/build.py --installer
; (defines AppVersion, SourceDir, OutputDir, IconFile are passed on the command line)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3C2B8E-9A41-4C55-8E0B-6D7A1F2C9B10}
AppName=MusicMaid
AppVersion={#AppVersion}
AppPublisher=MusicMaid
DefaultDirName={autopf}\MusicMaid
DefaultGroupName=MusicMaid
DisableProgramGroupPage=yes
; per-user install by default (no admin prompt); users can choose all-users
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename=MusicMaid-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\MusicMaid.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MusicMaid"; Filename: "{app}\MusicMaid.exe"
Name: "{autodesktop}\MusicMaid"; Filename: "{app}\MusicMaid.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MusicMaid.exe"; Description: "{cm:LaunchProgram,MusicMaid}"; Flags: nowait postinstall skipifsilent
