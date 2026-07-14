# Contributing to SafeVault

Thanks for helping improve SafeVault. Bug reports, documentation fixes, test
cases, and focused pull requests are welcome.

## Before You Start

- Search existing issues before opening a new one.
- Use Discussions for installation questions and general ideas.
- Use the security reporting process in [SECURITY.md](SECURITY.md) for
  vulnerabilities; do not disclose them in a public issue.
- Keep changes focused. Large behavioral changes should start with an issue or
  Discussion so the safety implications can be reviewed first.

## Development Setup

SafeVault uses Python 3.12.

```bash
python -m venv .venv
pip install -e '.[dev,ui,tray]'
```

Before submitting a pull request, run:

```bash
ruff check .
mypy src
pytest -q
```

## Safety Expectations

SafeVault protects user files, so changes must preserve its safety boundaries:

- never mutate the original project during `safevault run`;
- never apply deletions without explicit `--allow-delete` authorization;
- snapshot before restore overwrites and before applying sandbox changes;
- never follow symlinks outside a protected root;
- verify stored content hashes before returning or restoring content;
- never bypass operating-system permissions;
- never delete SafeVault's own database or object store.

See the [Safety Model](docs/zh/SAFETY_MODEL.md) for more context.

## Pull Requests

- Explain the user-visible problem and the chosen solution.
- Add or update tests for behavior changes.
- Update documentation when commands, UI behavior, or safety boundaries change.
- Keep unrelated formatting or refactoring out of the same pull request.
