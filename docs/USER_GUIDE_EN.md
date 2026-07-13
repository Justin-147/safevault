# SafeVault User Guide

SafeVault protects selected local folders continuously after onboarding. The
normal user flow is: install once, keep the daemon running, open Recovery Home
only when something needs to be restored.

## Daily Use

```bash
safevault ui --open
safevault daemon status
safevault backup status
```

The GUI home page shows protected folders, daemon health, recent deleted files,
recent modified files, the restore timeline, search, and quick restore actions.
Users do not need to know snapshot IDs for common recovery.

The status strip also shows local object-store use against the configured
storage budget. The v1.1.2 default target is 10 GB. Smart retention remains
planning/dry-run only, so SafeVault does not silently remove historical
versions.

## Manage Storage

Open **Storage** from Recovery Home to see the active data location, object and
total use, free disk space, the minimum needed for one latest restorable version
per file, per-root estimates, and the largest tracked files.

Changing the target changes warnings only. If the minimum already exceeds 10
GB, narrow protected folders and avoid replaceable media, installers, models,
datasets, and generated outputs. Never delete object-store files manually.

To move storage, choose an empty destination. SafeVault stops background
protection, checks free space, copies the database and objects, verifies them,
then switches the location. Select old-copy removal and type `MOVE STORAGE` only
when the original disk should be reclaimed. Failed verification leaves the
source intact. Deep verification of a large vault can take time.

Advanced users can run:

```bash
safevault storage status
safevault storage analyze
safevault storage budget 10
safevault storage migrate D:\SafeVaultData --remove-source --confirm "MOVE STORAGE"
```

## Protect Folders

During onboarding, choose common folders such as Desktop, Documents, Pictures,
and Projects. Later, add folders from the GUI or CLI:

```bash
safevault protect add C:\Users\you\Documents --profile documents
safevault roots
```

SafeVault refuses unsafe roots such as filesystem roots, `SAFEVAULT_HOME`, and
configured backup targets.

## Recover A Deleted File

Open `safevault ui --open`, find the file under recent deleted files, and choose
Restore. Normal restore uses a local confirmation action; destructive or
advanced operations still require explicit confirmation words.

## Recover From AI Or Bulk Changes

Run AI tools through SafeVault when possible:

```bash
safevault run --project C:\Users\you\Projects\app -- codex
safevault apply <sandbox-id> --dry-run
safevault apply <sandbox-id>
```

SafeVault records `before-ai-change` and `after-ai-change` restore points for
Codex, Cursor, Aider, Claude, Windsurf, and similar sandboxed AI coding
sessions. The watcher also marks high-volume edit batches as
`after-large-change`, so Recovery Home can show a timeline around risky changes.
Bursts of suspicious encrypted-file extensions create an
`emergency-mass-change` restore point and an error notification.

## Backup

Configure a backup target outside protected folders and outside
`SAFEVAULT_HOME`:

```bash
safevault backup configure --target E:\SafeVaultBackups --schedule daily
safevault backup run
safevault backup status
```

Use an external disk, NAS, or another machine for disk-failure protection.

## Pause Or Stop

```bash
safevault protect pause C:\Users\you\Documents --duration 30m
safevault protect resume C:\Users\you\Documents
safevault protect remove C:\Users\you\Documents --confirm
```

Pause and **Stop automatic protection** do not delete stored snapshots or
recovery history. The separate **Remove history permanently** action deletes
the root's database version and recovery indexes, so SafeVault can no longer
restore them; it requires a preview and typed root ID or full path.

The tray's **Quit SafeVault** action stops the daemon, Recovery Home, and tray
for the current session. Windows Startup settings control whether protection
starts again at the next sign-in.

To remove user Startup entries on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows_user.ps1
```

## Known Limits

SafeVault is local-only, not a remote admin console, not malware containment,
and not raw disk recovery. Store backups away from the protected machine for
disk-failure protection.
