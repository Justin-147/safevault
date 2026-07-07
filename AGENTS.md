# SafeVault Agent Instructions

SafeVault is a local file protection and recovery tool.

Safety rules:
- Never implement raw disk recovery in v1.
- Never mutate the original project during `safevault run`.
- Never apply deletions unless `--allow-delete` is explicitly passed.
- Always snapshot before restore overwrite.
- Always snapshot before applying sandbox changes.
- Never follow symlinks outside a protected root.
- Never apply external symlink placeholders over original symlinks.
- External symlink placeholders must be identified from sandbox sidecar metadata, not magic file content alone.
- Verify object-store content hashes before returning or restoring content.
- Require mandatory hashes in diff entries before applying them.
- Reject non-regular sandbox sources before hashing or copying them.
- Return CLI exit code 2 for apply conflicts, unsafe entries, or missing sources.
- Never bypass OS permissions.
- Never delete SafeVault's own database or object store.

Implementation rules:
- Use Python 3.12.
- Source code lives in `src/safevault`.
- Tests live in `tests`.
- CLI uses Typer.
- Terminal output uses Rich where helpful.
- Metadata uses SQLite.
- Content objects use BLAKE3 hashes.
- Tests must use temporary directories and `SAFEVAULT_HOME`.

Before declaring done, run:
- `ruff check .`
- `mypy src`
- `pytest -q`

If a test fails, fix the code or the test if the test is genuinely incorrect. Do not remove safety tests.
