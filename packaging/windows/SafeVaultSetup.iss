#define MyAppName "SafeVault"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SafeVault"
#define MyAppExeName "safevault.exe"

[Setup]
AppId={{A34C9F7B-454F-48A0-84DB-95BB868527B4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\SafeVault
DefaultGroupName=SafeVault
OutputDir=..\..\dist
OutputBaseFilename=SafeVaultSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\..\dist\safevault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SafeVault Recovery Home"; Filename: "{app}\{#MyAppExeName}"; Parameters: "ui --open"
Name: "{group}\SafeVault Tray"; Filename: "{app}\{#MyAppExeName}"; Parameters: "tray"
Name: "{userstartup}\SafeVault Daemon"; Filename: "{app}\{#MyAppExeName}"; Parameters: "daemon run"; Tasks: startup
Name: "{userstartup}\SafeVault Tray"; Filename: "{app}\{#MyAppExeName}"; Parameters: "tray"; Tasks: tray

[Tasks]
Name: "startup"; Description: "Start SafeVault automatically with Windows"; GroupDescription: "Startup:"; Flags: checkedonce
Name: "tray"; Description: "Start SafeVault tray with Windows"; GroupDescription: "Startup:"; Flags: checkedonce

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "daemon run"; Description: "Start SafeVault background protection"; Flags: nowait postinstall skipifsilent runhidden; Tasks: startup
Filename: "{app}\{#MyAppExeName}"; Parameters: "tray"; Description: "Start SafeVault tray"; Flags: nowait postinstall skipifsilent; Tasks: tray
Filename: "{app}\{#MyAppExeName}"; Parameters: "ui --open"; Description: "Launch SafeVault first-run wizard"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userstartup}\SafeVault Daemon.lnk"
Type: files; Name: "{userstartup}\SafeVault Tray.lnk"
Type: files; Name: "{userstartup}\SafeVault Daemon.cmd"
Type: files; Name: "{userstartup}\SafeVault Tray.cmd"
