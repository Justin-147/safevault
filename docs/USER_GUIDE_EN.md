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

## Pause Or Stop

```bash
safevault protect pause C:\Users\you\Documents --duration 30m
safevault protect resume C:\Users\you\Documents
safevault protect remove C:\Users\you\Documents --confirm
```

Pause and remove do not delete stored snapshots or object content.

## Known Limits

SafeVault is local-only, not a remote admin console, not malware containment,
and not raw disk recovery. Store backups away from the protected machine for
disk-failure protection.
