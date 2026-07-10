#define MyAppName "SafeVault"
#define MyAppVersion "1.0.2"
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
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\..\dist\safevault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "safevault-hidden.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SafeVault Recovery Home"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" ui --open"
Name: "{group}\SafeVault Tray"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" tray"
Name: "{userstartup}\SafeVault Daemon"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" daemon run"; Tasks: startup
Name: "{userstartup}\SafeVault Tray"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" tray"; Tasks: tray

[Tasks]
Name: "startup"; Description: "Start SafeVault automatically with Windows"; GroupDescription: "Startup:"; Flags: checkedonce
Name: "tray"; Description: "Start SafeVault tray with Windows"; GroupDescription: "Startup:"; Flags: checkedonce

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" daemon run"; Description: "Start SafeVault background protection"; Flags: nowait postinstall skipifsilent runhidden; Tasks: startup
Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" tray"; Description: "Start SafeVault tray"; Flags: nowait postinstall skipifsilent runhidden; Tasks: tray
Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" ui --open"; Description: "Launch SafeVault first-run wizard"; Flags: nowait postinstall skipifsilent runhidden

[UninstallDelete]
Type: files; Name: "{userstartup}\SafeVault Daemon.lnk"
Type: files; Name: "{userstartup}\SafeVault Tray.lnk"
Type: files; Name: "{userstartup}\SafeVault Daemon.cmd"
Type: files; Name: "{userstartup}\SafeVault Tray.cmd"
Type: files; Name: "{userstartup}\SafeVault Daemon.vbs"
Type: files; Name: "{userstartup}\SafeVault Tray.vbs"
