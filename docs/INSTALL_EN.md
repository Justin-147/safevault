# SafeVault Install Guide

SafeVault 1.1.1 provides stable local continuous file protection.
It keeps BLAKE3 object storage and SQLite metadata on the local machine.

## Install

```bash
python -m pip install -e '.[dev,ui]'
safevault ui --open
```

On Windows, the user-level helper can install the daemon startup item and
optionally the tray startup item:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_user.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_windows_user.ps1 -WithTray -OpenUi
```

The helper calls `safevault daemon install`, which writes a Startup-folder
command for the current Windows user. It does not install a kernel driver,
service account, browser extension, or remote access endpoint.

## Build SafeVaultSetup.exe

Release builders can create a one-click Windows installer with PyInstaller and
Inno Setup:

```powershell
python -m pip install -e '.[installer,ui,tray]'
powershell -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

The installer definition is `packaging/windows/SafeVaultSetup.iss` and produces
`dist/SafeVaultSetup.exe`. The installer registers current-user Startup entries
for the daemon and tray by default, starts background protection for the current
session, and launches the first-run wizard. Both Startup tasks can be disabled
during setup. Background protection, tray, and Recovery Home use hidden launchers
and should not leave terminal windows open.

Setup has a separate **SafeVault data location** page. This is where the
database and recoverable content live, not the application install directory.
When a D drive is present, setup suggests `D:\SafeVaultData`; choose any suitable
empty folder on a non-system drive. Upgrades never move an existing vault
silently. Use Recovery Home's Storage page after upgrading.

## First Run

Open the local GUI:

```bash
safevault ui --open
```

The onboarding flow recommends Documents, Desktop, and Pictures. Large project
workspaces are optional, and multiple custom paths can be added. Setup returns
immediately while the daemon builds initial recovery points in the background;
closing the browser does not stop protection.

Onboarding also shows the data location and the default 10 GB storage target.
The target is advisory rather than destructive: SafeVault never removes the
only restorable copy of a file merely to meet it.

Prefer specific personal or project folders over an entire drive or a large
workspace containing many projects. This keeps the initial scan and local object
store manageable.

## Uninstall Startup Items

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows_user.ps1
```

This removes SafeVault Startup-folder entries only. It does not delete snapshots,
objects, protected-root metadata, or backups.

## Safety Limits

SafeVault is not raw disk recovery and cannot recover files that were never
captured by a snapshot or watcher run. Keep exports or backups off-machine if
the local disk may fail.
