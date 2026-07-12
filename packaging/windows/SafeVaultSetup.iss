#define MyAppName "SafeVault"
#define MyAppVersion "1.1.1"
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
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
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

[Code]
var
  StoragePage: TInputDirWizardPage;
  ExistingVault: Boolean;

function StoragePointerPath(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}\.safevault-location');
end;

function DefaultLegacyStorage(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}\.safevault');
end;

procedure InitializeWizard();
var
  ExistingLocations: TArrayOfString;
  SuggestedLocation: String;
begin
  if LoadStringsFromFile(StoragePointerPath(), ExistingLocations) and
    (GetArrayLength(ExistingLocations) > 0) then
    SuggestedLocation := Trim(ExistingLocations[0])
  else
    SuggestedLocation := DefaultLegacyStorage();

  ExistingVault := FileExists(AddBackslash(SuggestedLocation) + 'vault.db') or
    FileExists(AddBackslash(DefaultLegacyStorage()) + 'vault.db');

  StoragePage := CreateInputDirPage(
    wpSelectDir,
    'SafeVault data location',
    'Choose where recoverable versions are stored',
    'Use a non-system drive when available. Existing installations must be moved from SafeVault Storage settings.',
    False,
    ''
  );
  StoragePage.Add('');
  if not ExistingVault then begin
    if DirExists('D:\') then
      SuggestedLocation := 'D:\SafeVaultData'
    else
      SuggestedLocation := ExpandConstant('{localappdata}\SafeVaultData');
  end;
  StoragePage.Values[0] := SuggestedLocation;
  if ExistingVault then begin
    StoragePage.Edits[0].Enabled := False;
    StoragePage.Buttons[0].Enabled := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  SelectedPath: String;
begin
  Result := True;
  if CurPageID <> StoragePage.ID then
    Exit;
  SelectedPath := RemoveBackslashUnlessRoot(ExpandFileName(StoragePage.Values[0]));
  if SelectedPath = ExtractFileDrive(SelectedPath) + '\' then begin
    MsgBox('SafeVault data cannot be stored at the root of a drive.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  StoragePage.Values[0] := SelectedPath;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  StorageLocations: TArrayOfString;
begin
  if (CurStep = ssPostInstall) and (not ExistingVault) then begin
    if not ForceDirectories(StoragePage.Values[0]) then
      RaiseException('SafeVault could not create the selected data folder.');
    SetArrayLength(StorageLocations, 1);
    StorageLocations[0] := StoragePage.Values[0];
    if not SaveStringsToUTF8FileWithoutBOM(
      StoragePointerPath(), StorageLocations, False
    ) then
      RaiseException('SafeVault could not save the selected data location.');
  end;
end;
