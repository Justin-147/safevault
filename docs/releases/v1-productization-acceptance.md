# SafeVault v1 Productization Acceptance

This checklist tracks the productization upgrade from engineering snapshot tool
to continuous local file protection.

## Installation

- Windows installer recipe produces `SafeVaultSetup.exe`.
- Installer registers current-user daemon Startup entry by default.
- Tray Startup entry remains optional.
- First-run wizard opens after install.

## Protection

- Onboarding can protect Desktop, Documents, Pictures, Projects, or custom
  folders.
- The daemon performs startup scans and watcher-triggered automatic saves.
- Users do not need to manage snapshot IDs for normal recovery.

## Recovery

- Recovery Home shows recent deleted files, recent modified files, timeline,
  search, and one-click restore.
- Recovery Center hides snapshot IDs, version IDs, and object hashes in normal
  UI labels.
- Multi-version restore remains available through hidden exact version IDs.

## AI And Mass Change

- `safevault run` records before/after AI restore points for known AI coding
  tools.
- Large change batches create `after-large-change` restore points.
- Suspicious encrypted-extension bursts create `emergency-mass-change` restore
  points and error notifications.

## Storage

- Smart retention protects latest versions, deletion markers, important
  restore points, hourly/daily recovery points, and AI/mass-change checkpoints.
- Dry-run cleanup estimates reclaimable object bytes without deleting data.

## Validation Commands

```bash
ruff check .
mypy src
pytest -q
python -m safevault --help
```
