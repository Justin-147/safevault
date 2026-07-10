# Changelog

## Unreleased

## 1.0.1 - 2026-07-10

SafeVault 1.0.1 is a Windows first-run reliability and usability release.

Fixed:
- The Windows installer, Startup entries, tray, and Recovery Home now launch
  through a hidden Windows launcher instead of leaving visible terminal windows.
- Packaged `safevault.exe` processes now start daemon/UI children directly;
  they no longer use the invalid frozen command `safevault.exe -m safevault`.
- First-run setup no longer blocks the browser while selected folders are fully
  scanned. It saves policies immediately and lets the daemon build initial
  recovery points in the background.
- Daemon status no longer reports a stale database `running`/`stopping` state
  when the corresponding process and lock do not exist.
- The browser favicon request now returns an intentional empty response instead
  of a noisy 404, and the broken static README status badge was removed.

Improved:
- Onboarding accepts multiple custom folder paths and explains that folders can
  be added or unprotected later.
- Large development workspaces remain discoverable but are no longer selected
  by default; generated test, cache, coverage, and review-render directories are
  ignored by default.
- Tray Quit stops background protection, the local UI, and the tray for the
  current session.
- Background child-process output is written under `SAFEVAULT_HOME/logs` for
  troubleshooting without showing consoles.

## 1.0.0 - 2026-07-10

SafeVault 1.0.0 turns the existing snapshot and object-store foundation into a
continuous local protection product with a recovery-first interface. The core
BLAKE3 object store, SQLite metadata model, conservative restore behavior, and
sandbox apply safety boundaries remain unchanged.

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
- `safevault.retention_engine` adds dry-run smart cleanup estimates, including
  reclaimable object bytes without counting objects still referenced by protected
  or important versions.
- Recovery Home now shows a restore timeline backed by continuous protection
  metadata, so users can browse recent file changes alongside deleted and
  modified file lists.
- Recovery Center history now shows user-facing restore-point labels instead of
  snapshot/version IDs or object hashes, while keeping exact version IDs hidden
  for restore submissions.
- AI/Codex protection mode records `before-ai-change` and `after-ai-change`
  restore points for sandboxed Codex/Cursor commands, plus important
  `after-large-change` restore points when the watcher sees high-volume edits.
- AI workflow detection now recognizes additional common coding assistants such
  as Aider, Claude, Copilot, Cline, and Windsurf by command name.
- Mass-change protection now detects bursts of suspicious encrypted-file
  extensions and records an important `emergency-mass-change` restore point with
  an error notification.
- Productization docs now include English and Chinese install/user guides plus
  conservative Windows user-startup helper scripts for daemon/tray setup.
- Documentation now includes a `docs/README.md` index and expanded English and
  Chinese user guides covering startup, folder protection, restore, pause,
  disable, backup, limitations, AI rollback, and mass-change recovery.
- Release acceptance documentation and tests now cover the v1 productization
  pillars across installation, protection, recovery, AI/mass-change handling,
  retention, and validation commands.

Release hardening:
- Documentation now has one bilingual entry point, one user guide and FAQ per
  language, and a smaller advanced section; obsolete duplicate guides and the
  completed internal implementation plan are no longer shipped.
- GUI help links to the same core guides as the repository README, while
  maintainer acceptance material is kept outside end-user documentation.
- Removed unused platform placeholder modules and a no-op static script.
- Windows Startup commands now work in both Python and frozen PyInstaller
  installations and avoid duplicate `.cmd` entries when installer shortcuts
  already exist.
- The Windows installer starts background protection after installation, enables
  the tray task by default, and removes both shortcut and command startup files
  during uninstall.
- First-run recommendations include Pictures and hide Windows-only startup
  controls on unsupported platforms.
- Recovery Home reports the real background state and displays local object-store
  usage against the configured storage budget.
- English and Chinese FAQ/release documentation complete the v1 documentation
  set.
- The release-check script uses an isolated temporary `SAFEVAULT_HOME` and does
  not run daemon smoke checks against a user's live vault.

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
