#!/usr/bin/env bash
set -euo pipefail

ruff check .
mypy src
pytest -q
python -m safevault --help
python -m safevault --version
python - <<'PY'
from safevault.ui.app import create_app
app = create_app(token="test-token")
assert app is not None
print("ui app ok")
PY
bash scripts/smoke.sh
bash scripts/gui_smoke.sh
python -m build
python - <<'PY'
from pathlib import Path
import zipfile

wheel = next(Path("dist").glob("*.whl"))
names = set(zipfile.ZipFile(wheel).namelist())
required = [
    "safevault/ui/templates/base.html",
    "safevault/ui/templates/dashboard.html",
    "safevault/ui/static/safevault.css",
    "safevault/ui/docs/README.zh-CN.md",
    "safevault/ui/docs/zh/GUI_GUIDE.md",
    "safevault/ui/docs/zh/USER_MANUAL.md",
]
missing = [name for name in required if name not in names]
if missing:
    raise SystemExit(f"wheel missing GUI/doc assets: {missing}")
print("wheel assets ok")
PY
python -m twine check dist/*
