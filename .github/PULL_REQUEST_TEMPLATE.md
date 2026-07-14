## What changed

Describe the focused change and the user-visible problem it solves.

## Safety impact

- [ ] This change does not weaken SafeVault's deletion, restore, symlink, hash,
      permission, or original-project safety rules.
- [ ] I described any file overwrite, deletion, migration, or external-path
      behavior introduced by this change.

## Validation

- [ ] `ruff check .`
- [ ] `mypy src`
- [ ] `pytest -q`
- [ ] Documentation and tests were updated where needed.
