# SafeVault

SafeVault is a local file-protection and recovery tool for project directories.
It captures versioned snapshots, stores file content in a BLAKE3-addressed
object store, records file versions and deletion markers in SQLite, restores
captured versions, and runs risky commands in a disposable project copy.

SafeVault can restore only versions that were already captured by SafeVault
snapshots. It is not a replacement for system backups or off-machine backups.

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
pip install -e .[dev]
```

SafeVault requires Python 3.12 and the `blake3` package.

## Quickstart

```bash
safevault init ~/Projects/myapp
safevault snapshot ~/Projects/myapp --reason initial
safevault versions ~/Projects/myapp/file.py
safevault restore ~/Projects/myapp/file.py --latest
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
resolve inside the sandbox copy.

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
safevault doctor --json
safevault prune --dry-run
safevault prune
```

Doctor reports ERROR-level integrity problems such as missing referenced
objects, missing required tables, and missing registered roots. WARN-level
findings include orphan objects, temp files, and incomplete sandbox directories;
warnings are visible but not fatal.

Prune is conservative. It deletes only object-store files that look like valid
content hashes and are not referenced by any version. It never deletes the
database, logs, temp root, sandboxes, or invalid object filenames.

## Validation

```bash
ruff check .
mypy src
pytest -q
python -m safevault --help
```

## Limitations

- No raw disk recovery.
- Recovery is limited to previously captured snapshots.
- `safevault run` is not a hardened malicious-code sandbox.
- No off-machine backup.
- The watcher is best-effort and snapshots remain the source of recovery.
- Prune only deletes unreferenced content objects.
