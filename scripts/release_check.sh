#!/usr/bin/env bash
set -euo pipefail

ruff check .
mypy src
pytest -q
python -m safevault --help
python -m safevault --version
python -m safevault daemon run --test-once
python -m safevault tray --check
python - <<'PY'
from safevault.ui.app import create_app
app = create_app(token="test-token")
assert app is not None
print("ui app ok")
PY
bash scripts/smoke.sh
bash scripts/gui_smoke.sh
python scripts/onboarding_smoke.py
rm -rf dist
python -m build
python - <<'PY'
from pathlib import Path
import zipfile

wheel = next(Path("dist").glob("*.whl"))
names = set(zipfile.ZipFile(wheel).namelist())
required = [
    "safevault/ui/templates/base.html",
    "safevault/ui/templates/dashboard.html",
    "safevault/ui/templates/onboarding.html",
    "safevault/ui/static/safevault.css",
    "safevault/ui/docs/README.zh-CN.md",
    "safevault/ui/docs/zh/GUI_GUIDE.md",
    "safevault/ui/docs/zh/USER_MANUAL.md",
    "safevault/ui/docs/zh/auto-protection.md",
    "safevault/ui/docs/zh/daemon-tray.md",
    "safevault/ui/docs/zh/one-click-restore.md",
    "safevault/ui/docs/zh/automatic-backup.md",
    "safevault/ui/docs/zh/onboarding.md",
]
missing = [name for name in required if name not in names]
if missing:
    raise SystemExit(f"wheel missing GUI/doc assets: {missing}")
print("wheel assets ok")
PY
python -m twine check dist/*
