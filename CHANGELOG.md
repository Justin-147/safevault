# Changelog

## Unreleased

Added:
- Windows productization assets: a shared startup integration module, first-run
  startup choice, and Inno Setup packaging script for building
  `SafeVaultSetup.exe`.
- Continuous protection metadata tables for file events, version timeline
  entries, and restore points while keeping the existing BLAKE3 object store and
  SQLite snapshot/version model.
- Continuous protection tests now cover watcher-triggered automatic save points
  becoming regular recoverable versions.
- Smart retention planning that balances high-frequency recent versions,
  hourly/daily recovery points, latest file versions, and important checkpoints
  without deleting data automatically.
- Recovery Home now shows a restore timeline backed by continuous protection
  metadata, so users can browse recent file changes alongside deleted and
  modified file lists.
- AI/Codex protection mode records `before-ai-change` and `after-ai-change`
  restore points for sandboxed Codex/Cursor commands, plus important
  `after-large-change` restore points when the watcher sees high-volume edits.
- Productization docs now include English and Chinese install/user guides plus
  conservative Windows user-startup helper scripts for daemon/tray setup.

## 0.2.0rc1

SafeVault 0.2.0rc1 introduces automatic protection mode while remaining a
release candidate.

Added:
- `safevault protect` commands for add/list/remove/auto-detect/pause/resume.
- Config file support at `SAFEVAULT_HOME/config.toml` with atomic writes.
- SQLite migrations for protection policies, daemon state, change batches,
  backup jobs, and notifications.
- `safevault recent` and `safevault search`.
- `safevault daemon` with single-instance lock, heartbeat, startup scan,
  debounced watcher snapshots, immediate deleted markers, scheduled snapshots,
  idle verify, and bulk-delete notifications.
- `safevault backup` with configure/status/run/disable and scheduled export.
- Recovery Home, onboarding, one-click normal restore, and backup status in the
  local GUI.
- Optional `safevault tray` command through the `[tray]` extra.
- Chinese documentation for automatic protection, daemon/tray, one-click
  restore, automatic backup, and onboarding.

Safety notes:
- Automatic protection does not delete user files.
- Backup targets are rejected inside `SAFEVAULT_HOME` and protected roots.
- GUI restore no longer requires `RESTORE` in normal mode, but still requires a
  local confirmation action; advanced and legacy flows still accept `RESTORE`.
- Import/apply/export/prune destructive protections remain unchanged.

## 0.1.0rc1

SafeVault is a local project protection and recovery tool built around
versioned snapshots, a BLAKE3-addressed object store, restore, sandboxed command
runs, and conservative apply flows.

Safety guarantees:
- `safevault run` operates on a copied working tree and does not mutate the
  original project.
- `safevault apply` skips deletions unless `--allow-delete` is passed.
- The local GUI binds to localhost by default and requires a random token.
- GUI restore, export overwrite, export skip-verify, sandbox cleanup, apply
  delete, import, and prune flows require typed confirmation words.
- Object-store reads and restores verify BLAKE3 content hashes.
- External symlink placeholders are tracked by sandbox sidecar metadata.
- `unprotect` and `sandbox-clean` require explicit confirmation for destructive
  metadata or sandbox cleanup.

Known limitations:
- No raw disk recovery.
- Not a hardened malware sandbox.
- The GUI is local-only and not a remote admin console.
- No continuous cross-machine sync.
- Retention is planning-only in this release candidate.
- Export/import exists, but archives should still be stored off-machine.
- Import requires a trusted export archive and an empty target home unless
  `--overwrite` is explicitly passed.

Added:
- Local FastAPI GUI for roots, snapshots, restore, sandboxes, maintenance, and
  export/import workflows.
- Chinese README and user documentation under `docs/zh`.
- GUI security smoke test for local HTTP dashboard access.

Security hardening:
- GUI restore/export/sandbox-clean confirmations were tightened for RC1.
- GUI import dry-run checkbox semantics now match real browser form submission,
  so unchecking dry-run can perform a confirmed import after typing `IMPORT`.
- Release checks verify GUI/doc assets inside the built wheel.

Upgrade notes:
- Run `safevault doctor --deep` and `safevault verify --deep` after upgrading.
- Create an off-machine export with `safevault export --output <path> --gzip`.
