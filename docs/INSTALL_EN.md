# SafeVault Install Guide

SafeVault 0.2.0rc1 is a release candidate for local continuous file protection.
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
for the daemon by default, offers optional tray startup, and launches the
first-run wizard after install.

## First Run

Open the local GUI:

```bash
safevault ui --open
```

The onboarding flow lets the user select Documents, Desktop, Projects, Pictures,
or other folders. SafeVault creates initial snapshots for selected folders and
can configure an external backup target.

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
