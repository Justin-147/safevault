# Changelog

## Unreleased

## 1.1.9 - 2026-07-14

Added:
- Recovery Home Storage now provides a seven-day retention setting, an explicit
  automatic-cleanup opt-in, a safety confirmation, a cleanup preview, and the
  latest cleanup result.
- The daemon can run authorized retention cleanup at most once per day.

Safety:
- Automatic cleanup is disabled until the user explicitly enables it with
  `ENABLE AUTO CLEANUP`.
- Cleanup removes only old superseded versions. It preserves each file's latest
  restorable content, deleted-file recovery content, important restore points,
  AI change restore points, and all history inside the configured window.
- Object files are removed only after their final database reference is deleted;
  symlinked or non-regular object paths are skipped.

Changed:
- The default retention window is seven days. Existing untouched 90-day
  defaults migrate to seven days without enabling deletion automatically.

## 1.1.8 - 2026-07-14

Fixed:
- Tray actions now use a lightweight authenticated health endpoint instead of
  repeatedly rendering the database-backed Recovery Home while waiting for the
  local UI to start.
- `Open SafeVault` and `Recent Deleted` no longer create additional local UI
  processes when a slow dashboard request exceeds the readiness timeout.
- Windows falls back to the system default URL handler when Python's browser
  launcher reports that it could not open the requested SafeVault page.

Safety:
- The new health endpoint still requires the per-session UI token and does not
  expose vault status, paths, or file metadata.

## 1.1.7 - 2026-07-14

Fixed:
- Tray actions no longer open Recovery Home with a stale token after another UI
  process fails to bind the default port.
- A UI process checks that its requested port is available before replacing the
  registered session, preserving the active session on bind conflicts.
- When the registered session is stale and port 8765 is occupied, the tray
  selects the next available local port instead of repeatedly launching a UI
  process that cannot start.
- The Recent Deleted tray action now opens `/deleted` instead of the home page.

## 1.1.6 - 2026-07-14

Fixed:
- The Recent Deleted page now converts UTC timestamps to the browser's local
  time zone instead of displaying raw UTC values.
- A temporary SQLite busy or locked error during a watcher delete callback no
  longer terminates the filesystem observer thread. SafeVault retries once and
  leaves final reconciliation to the scheduled snapshot if the lock persists.

Improved:
- The Recent Deleted page refreshes automatically every five seconds, so files
  deleted after the page was opened appear without a manual browser refresh.
- The page identifies the active local UTC offset and IANA time-zone name and
  uses clearer Chinese labels for filtering and restore actions.

## 1.1.5 - 2026-07-13

Fixed:
- Removing history for a large protected folder no longer performs repeated
  full-table scans for every version and file row.
- History removal now obtains the SQLite write lock before starting and waits
  briefly for active background writes instead of failing mid-request.
- Database lock and deletion errors are shown as readable Recovery Home
  messages; failed transactions are rolled back instead of returning a raw
  Internal Server Error page.

Performance:
- Added indexes for all snapshot, file, and version foreign keys involved in
  root removal. On a copy of a real vault with about 6,700 files and versions,
  removal time fell from about 82 seconds to about 4 seconds.

## 1.1.4 - 2026-07-13

Added:
- Recovery Home now lists SafeVault-created external backup archives with their
  size and modification time.
- External backup archives can be deleted individually from Backup Management,
  and automatic backup can be stopped without deleting existing archives.

Improved:
- Protect Folders now exposes Stop Protection and Delete History actions
  directly in the folder list.
- Permanent history removal uses a clear impact preview and final confirmation
  instead of requiring users to type a root ID or full path.
- Successful history removal returns directly to the protected-folder list.

Safety:
- History removal continues to leave the original protected folder untouched.
- Backup deletion accepts only regular SafeVault archive files directly inside
  the configured external backup directory; traversal paths, symlinks, and
  unrelated files are rejected.

## 1.1.3 - 2026-07-13

Fixed:
- Recovery Home now refreshes recent deletions and modifications every five
  seconds, so a deleted Desktop file appears without reopening or manually
  refreshing the page.
- Recent activity returned by the live dashboard remains limited to one latest
  modification per file.
- Pytest temporary directories are ignored by default so development test runs
  do not pollute recovery history or consume object-store space.

Improved:
- Recovery Home displays deletion and modification timestamps in local time.
- Advanced navigation now uses the clearer labels AI Change Protection, Health
  & Cleanup, and External Backup, with short explanations on hover.
- User guides explain live updates and why a file must have been captured before
  it can be restored.

## 1.1.2 - 2026-07-13

Changed:
- Upgrades with an existing vault now show a clear bilingual explanation page
  instead of a disabled data-location picker.
- After an upgrade, Setup opens Recovery Home directly on Storage management so
  the user can migrate existing data with copy, integrity verification, and an
  explicit old-copy removal choice.
- Fresh installations still allow the recovery-data location to be selected in
  Setup.

Fixed:
- The installer no longer presents an intentionally locked field as though the
  folder picker were broken.
- The local UI can safely open the Storage page whether it is already running or
  is started by Setup.

## 1.1.1 - 2026-07-12

Fixed:
- The Windows installer now resolves the profile directory through the supported
  `{%USERPROFILE}` environment-variable constant. v1.1.0 used the unsupported
  `{userprofile}` constant and stopped with a runtime error before setup.
- Installer tests now reject the unsupported constant so the failure cannot
  return unnoticed.

## 1.1.0 - 2026-07-12

SafeVault 1.1.0 prevents recovery history from unexpectedly filling the system
drive and adds a verified path for moving an existing vault.

Added:
- The Windows installer asks where SafeVault recovery data should be stored and
  recommends a non-system drive when one is available.
- Recovery Home now has a Storage page showing the active data location, object
  store size, free space, target budget, per-root minimum storage estimates, and
  the largest tracked files.
- Existing vaults can be migrated to a new empty folder. Migration stops
  background protection, checks free space, copies a transactionally consistent
  SQLite database, verifies object hashes, switches the location atomically, and
  deletes the old copy only after explicit confirmation.
- `safevault storage status`, `analyze`, `budget`, and `migrate` provide the same
  storage controls for advanced users.

Changed:
- New installations use a 10 GB storage target instead of 100 GB. The target is
  deliberately soft: SafeVault never deletes the last restorable version merely
  to reach the number.
- Child-process logs are stored in a small runtime directory outside the movable
  vault, allowing Windows to release the old data folder after migration.
- The storage-location pointer uses UTF-8 and supports non-ASCII Windows paths.

## 1.0.3 - 2026-07-11

SafeVault 1.0.3 fixes Windows background-status reporting and closes a startup
monitoring gap discovered during first-run testing with large protected roots.

Fixed:
- Windows process detection now uses the native process API instead of
  `os.kill(pid, 0)`, which incorrectly reported a live daemon as stopped.
- The filesystem observer starts before startup reconciliation, so changes in
  an already-scanned folder are not missed while another large folder is still
  being scanned.
- Recent Deleted shows each currently deleted file once. Restored files no
  longer remain in that list, while their history remains available elsewhere.
- Recovery Home shows only the latest recent-modification entry per file, so a
  frequently updated file cannot fill the whole panel.

## 1.0.2 - 2026-07-10

SafeVault 1.0.2 clarifies and separates two different protected-folder actions.

Fixed:
- Recovery Home no longer describes destructive root metadata removal as if
  recoverable history were preserved.

Improved:
- A new “Stop automatic protection” action disables monitoring while preserving
  snapshots, versions, and recovery points.
- Destructive unprotect is labeled “Remove history permanently,” explains that
  database recovery indexes are deleted, and retains the existing typed
  confirmation and dry-run preview.

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
