# SafeVault

[![CI](https://github.com/Justin-147/safevault/actions/workflows/ci.yml/badge.svg)](https://github.com/Justin-147/safevault/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Justin-147/safevault?include_prereleases&label=release)](https://github.com/Justin-147/safevault/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-FastAPI-009688.svg)](README.md#graphical-ui)
[![Docs](https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-blue.svg)](README.zh-CN.md)
[![Status](https://img.shields.io/badge/status-rc1-orange.svg)](CHANGELOG.md)

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)
SafeVault is a local file-protection and recovery tool for project directories.
It captures versioned snapshots, stores file content in a BLAKE3-addressed
object store, records file versions and deletion markers in SQLite, restores
captured versions, and runs risky commands in a disposable project copy.

SafeVault can restore only versions that were already captured by SafeVault
snapshots. Content objects are addressed by BLAKE3 hash and verified before
read or restore. It is not a replacement for system backups or off-machine
backups.

## Release Status

SafeVault `v0.1.0rc1` is a release candidate, not a stable/final release. The
corresponding Git tag may be named `v0.1.0-rc1`, while Python package metadata
uses the PEP 440 version `0.1.0rc1`.

SafeVault is suitable for cautious personal/project use after you have verified:

- CI passes on your target platform.
- `safevault verify --deep` is healthy.
- You have tested export/import round-trip restore.
- You store export archives off-machine.

SafeVault is not a hardened malware sandbox and not a replacement for OS backups.

Operational checklist:

```bash
safevault doctor --deep
safevault verify --deep
safevault export --output /external/safevault-export.tar.gz --gzip
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --dry-run
```

Write exports to an external disk or sync them off-machine.

## What It Does Not Do

SafeVault v1 does not perform raw disk recovery and does not parse NTFS, APFS,
ext4, btrfs, ZFS, or other filesystem internals. Raw disk recovery is
platform-specific and easy to make destructive, so this project only restores
content already present in SafeVault's own object store.

`safevault run` protects the original project directory from accidental
modifications by running commands in a copied working tree. It is not a hardened
security sandbox for malicious code. Commands can still access the user's
filesystem, network, environment variables, and credentials unless the operating
system or an external container blocks them.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e .[dev,ui]
```

SafeVault requires Python 3.12 and the `blake3` package.

## Graphical UI

```bash
safevault ui --open
```

The UI binds to `127.0.0.1` by default and uses a random token printed at
startup. It is a local convenience UI, not a remote admin console. Do not expose
it to public networks.

High-risk GUI actions require typed confirmation words: `RESTORE`,
`ALLOW DELETE`, `PRUNE`, `CLEAN SANDBOXES`, `OVERWRITE EXPORT`,
`SKIP VERIFY`, `IMPORT`, and `OVERWRITE`. The GUI calls the same backend safety
logic as the CLI.

The release check includes a real local HTTP smoke test:

```bash
bash scripts/gui_smoke.sh
```

GUI import is dry-run by default. To perform a real import in the browser,
uncheck dry-run and type `IMPORT`; importing over a non-empty target additionally
requires `OVERWRITE`. The project remains `0.1.0rc1`, a release candidate, not a
stable/final release.

## Quickstart

```bash
safevault init ~/Projects/myapp
safevault snapshot ~/Projects/myapp --reason initial
safevault versions ~/Projects/myapp/file.py
safevault restore ~/Projects/myapp/file.py --latest
safevault status ~/Projects/myapp
safevault verify --deep
```

By default SafeVault stores data in `~/.safevault`. Set `SAFEVAULT_HOME` to use
another location:

```bash
SAFEVAULT_HOME=/tmp/safevault-test safevault doctor
```

## Snapshots And Restore

Snapshots walk the protected root without following symlinks, skip ignored
paths, stream file content into the object store, and record file versions in
SQLite. Files that disappear between snapshots receive deletion markers.

Restore can restore the latest non-deleted version or a specific version id:

```bash
safevault restore ~/Projects/myapp/file.py --latest
safevault restore ~/Projects/myapp/file.py --version 12
safevault restore ~/Projects/myapp/file.py --version 12 --to /tmp/file.py
```

Before overwriting a protected file, SafeVault snapshots the current protected
root. After restoring inside a protected root, it snapshots again so metadata
reflects the restored content.

## Sandbox Workflow

```bash
safevault run --project ~/Projects/myapp -- codex
safevault sandboxes --latest
safevault apply <sandbox-id> --dry-run
safevault apply <sandbox-id>
safevault apply <sandbox-id> --allow-delete
```

`safevault run` snapshots the project, copies it to
`SAFEVAULT_HOME/sandboxes/<sandbox-id>/work`, runs the command there, and writes
`diff.json`. The original project is not modified by `run`.

External symlinks are not preserved as active symlinks in the sandbox. If a
project symlink points outside the protected root, SafeVault writes a regular
placeholder file instead, preventing sandbox commands from writing through that
link to outside files. Internal symlinks are preserved only when they still
resolve inside the sandbox copy. External symlink placeholders are recorded in
`SAFEVAULT_HOME/sandboxes/<sandbox-id>/placeholder-map.json`; ordinary files are
not treated as placeholders merely because their content starts with a
SafeVault sentinel.

If an external symlink is not modified by the sandbox command, it is treated as
unchanged and does not appear in the sandbox diff. `safevault apply` also refuses
to copy an external-symlink placeholder back over the original symlink. If a
sandbox command turns that placeholder into an ordinary file, SafeVault treats
the file-kind change as unsafe and preserves the original symlink.

`diff.json` uses schema version `1` and includes creation time, the original
root, the sandbox work root, the SafeVault version, entries, and
created/modified/deleted counts. Unsupported schema versions or root metadata
that does not match the sandbox record are rejected before apply begins.

## Apply Behavior

`safevault apply` treats `diff.json` as untrusted input. It validates relative
paths, rejects absolute or parent-escaping paths, rejects protected and ignored
paths for all change types, validates file kinds and hashes, and refuses unsafe
symlinks.

Use `safevault apply <sandbox-id> --dry-run` to validate a sandbox diff without
changing files, taking pre/post apply snapshots, or changing sandbox status.

Created and modified files are copied back with atomic replace only after their
mandatory hashes match. Deletions are skipped unless `--allow-delete` is
explicitly passed. Even with `--allow-delete`, SafeVault never deletes protected
paths such as `.git`, `.safevault`, `node_modules`, `.venv`, `venv`, `dist`,
`build`, or `target`.

SafeVault also detects conflicts. If the original project changed after
`safevault run`, apply skips that entry instead of overwriting user work. After
successful writes or deletions, SafeVault snapshots the original project with
reason `post-apply`.

Apply exit codes are intended for automation:

- `0`: completed successfully, including the normal case where deletions were
  skipped because `--allow-delete` was not passed.
- `1`: expected SafeVault user error, such as an unknown sandbox id.
- `2`: apply found conflicts, unsafe entries, or missing sandbox sources.

Diff entries must include required hash metadata: created entries require
`new_hash`, modified entries require `old_hash` and `new_hash`, and deleted
entries require `old_hash`. Sandbox sources are classified without following
symlinks; directories, FIFOs, sockets, devices, and other special files are
rejected before hashing or copying.

## Doctor And Prune

```bash
safevault doctor
safevault doctor --deep
safevault doctor --json
safevault verify
safevault verify --deep
safevault prune --dry-run
safevault prune
```

Doctor reports ERROR-level integrity problems such as missing referenced
objects, invalid referenced object hashes, missing required tables, and missing
registered roots. `doctor --deep` also recomputes referenced object hashes and
may be slow on large vaults. WARN-level findings include orphan objects, temp
files, and incomplete sandbox directories; warnings are visible but not fatal.

`safevault verify` performs a fast referenced-object check. `safevault verify
--deep` is the dedicated full integrity check; it recomputes hashes for
referenced objects and exits nonzero if any referenced object is missing,
invalid, or corrupted.

Prune is conservative. It deletes only object-store files that look like valid
content hashes and are not referenced by any version. It never deletes the
database, logs, temp root, sandboxes, or invalid object filenames. In dry-run
mode it reports `Would delete objects` and `Would reclaim bytes` without
removing files.

## Management

```bash
safevault roots
safevault status ~/Projects/myapp
safevault unprotect ~/Projects/myapp --dry-run
safevault unprotect ~/Projects/myapp --confirm
safevault sandbox-clean --older-than 30d --status applied --dry-run
safevault sandbox-clean --older-than 30d --status applied --confirm
safevault export --output /tmp/safevault-export.tar.gz --gzip
safevault import --input /tmp/safevault-export.tar.gz --target-home /tmp/safevault-restore --dry-run
safevault import --input /tmp/safevault-export.tar.gz --target-home /tmp/safevault-restore --confirm
safevault retention-plan --keep-days 90
```

`roots` lists registered protected roots. `status` shows root metadata, latest
snapshot, tracked active/deleted counts, object-store size, latest sandbox, and
health summary. `unprotect` is destructive metadata cleanup, so it requires
`--confirm`; `--dry-run` prints row counts and object-store content files are not
deleted. `sandbox-clean` defaults to dry-run and removes only sandbox
directories matching both age and status filters when `--confirm` is passed.
`export` writes a vault archive containing a transactionally consistent
`vault.db` backup, referenced object files, and a manifest. For RC1, exports
include referenced objects only and intentionally exclude orphan objects.
`import` defaults to a dry-run unless `--confirm` is passed; dry-run performs
the full validation path, including archive member paths and types, manifest
schema, database integrity, object counts, referenced object presence, and object
hash contents. Import trusted archives into a fresh target home whenever
possible; importing into the current live `SAFEVAULT_HOME` or inside it is
rejected. `retention-plan` is non-destructive and reports old versions that a
future retention policy could remove.

The GUI import form mirrors this safety model: it is checked as dry-run by
default. A confirmed browser import requires unchecking dry-run and typing
`IMPORT`; GUI overwrite requires typing `OVERWRITE`.

Export/import round-trip:

```bash
safevault export --output /external/safevault-export.tar.gz --gzip
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --dry-run
safevault import --input /external/safevault-export.tar.gz --target-home /tmp/safevault-imported --confirm
SAFEVAULT_HOME=/tmp/safevault-imported safevault verify --deep
SAFEVAULT_HOME=/tmp/safevault-imported safevault doctor --deep
```

Import only archives you created or otherwise trust.

## Validation

```bash
ruff check .
mypy src
pytest -q
python -m safevault --help
python -m safevault --version
bash scripts/smoke.sh
bash scripts/release_check.sh
python -m build
python -m twine check dist/*
```

Release checklist for `v0.1.0-rc1`:

- Linux CI, macOS symlink CI, and Windows core CI are green.
- README release status says release candidate, not stable/final.
- `CHANGELOG.md`, `pyproject.toml`, and `safevault.__version__` agree on
  `0.1.0rc1`.
- Export/import round-trip works in a clean environment.
- Export archives are stored off-machine.

## Limitations

- No raw disk recovery.
- Recovery is limited to previously captured snapshots.
- `safevault run` is not a hardened malicious-code sandbox.
- No continuous sync or built-in off-machine backup.
- Import archives must be trusted.
- The watcher is best-effort and snapshots remain the source of recovery.
- Retention is planning-only in this release candidate.
- Prune only deletes unreferenced content objects.

