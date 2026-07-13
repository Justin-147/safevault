#define MyAppName "SafeVault"
#define MyAppVersion "1.1.2"
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
Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" ui --open"; Description: "Launch first-time setup / 打开首次设置"; Flags: nowait postinstall skipifsilent runhidden; Check: ShouldOpenFirstRun
Filename: "{sys}\wscript.exe"; Parameters: """{app}\safevault-hidden.vbs"" ui --open --page storage"; Description: "Open storage migration / 打开存储迁移"; Flags: nowait postinstall skipifsilent runhidden; Check: ShouldOpenStorageMigration

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
  ExistingStoragePage: TOutputMsgWizardPage;
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

  if FileExists(AddBackslash(SuggestedLocation) + 'vault.db') then
    ExistingVault := True
  else if FileExists(AddBackslash(DefaultLegacyStorage()) + 'vault.db') then begin
    SuggestedLocation := DefaultLegacyStorage();
    ExistingVault := True;
  end
  else
    ExistingVault := False;

  StoragePage := CreateInputDirPage(
    wpSelectDir,
    'SafeVault data location / 数据位置',
    'Choose where recoverable versions are stored / 选择可恢复版本的存放位置',
    'Use an empty folder on a non-system drive when available. / 建议选择非系统盘上的空文件夹。',
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
  ExistingStoragePage := CreateOutputMsgPage(
    StoragePage.ID,
    'Existing SafeVault data detected / 检测到现有数据',
    'This upgrade keeps the current data location / 本次升级保留当前位置',
    'Current location / 当前位置:' + #13#10 + SuggestedLocation + #13#10#13#10 +
    'To protect existing recovery data, Setup will not move it while upgrading. ' +
    'After installation, SafeVault will open Storage management so you can choose ' +
    'an empty folder on another drive and run a verified migration.' + #13#10#13#10 +
    '为避免升级过程中损坏已有恢复数据，安装器不会直接搬移。安装完成后将自动打开“存储管理”，' +
    '你可以选择其他磁盘上的空文件夹并执行带校验的迁移。请勿手动剪切数据目录。'
  );
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = StoragePage.ID) and ExistingVault) or
    ((PageID = ExistingStoragePage.ID) and (not ExistingVault));
end;

function ShouldOpenFirstRun(): Boolean;
begin
  Result := not ExistingVault;
end;

function ShouldOpenStorageMigration(): Boolean;
begin
  Result := ExistingVault;
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
