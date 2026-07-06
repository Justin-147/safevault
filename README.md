# SafeVault

SafeVault is a local file-protection and recovery tool. It records selected
directories in SQLite, stores file content in a content-addressed object store,
tracks versions and deletions, restores files from captured snapshots, and runs
risky commands in a disposable sandbox copy of a project.

SafeVault v1 does not perform raw disk recovery. It cannot recover files that
were never captured by a SafeVault snapshot. Raw disk recovery is intentionally
out of scope because it is platform-specific, destructive when done poorly, and
requires permissions and filesystem behavior that a safe MVP should not assume.

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

## Basic Usage

```bash
safevault init ~/Projects/myapp
safevault snapshot ~/Projects/myapp --reason manual
safevault versions ~/Projects/myapp/file.py
safevault restore ~/Projects/myapp/file.py --latest
```

## Sandbox Usage

```bash
safevault run --project ~/Projects/myapp -- codex
safevault apply <sandbox-id>
safevault apply <sandbox-id> --allow-delete
```

`safevault run` copies the project into `SAFEVAULT_HOME/sandboxes` and runs the
command there. The original project directory is not modified. `safevault apply`
copies created and modified files back to the original project. Deletions are
skipped by default and require `--allow-delete`.

## SafeVault Home

SafeVault stores metadata under `~/.safevault` by default:

```text
vault.db
objects/
logs/
sandboxes/
tmp/
```

Set `SAFEVAULT_HOME` to use another location, which is especially useful in
tests:

```bash
SAFEVAULT_HOME=/tmp/safevault-test safevault doctor
```

## Limitations

- No raw disk recovery in v1.
- Recovery is limited to content already captured in SafeVault snapshots.
- The watcher is best-effort and triggers full snapshots after debounced events.
- Prune is conservative and only deletes objects not referenced by any version.
- Symlinks are recorded by link target text and are never followed.

## Validation

```bash
ruff check .
mypy src
pytest -q
python -m safevault --help
```
