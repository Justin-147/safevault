#!/usr/bin/env bash
set -euo pipefail

AUDIT_TMP="$(mktemp -d)"
cleanup() {
  rm -rf "$AUDIT_TMP"
}
trap cleanup EXIT
export SAFEVAULT_HOME="$AUDIT_TMP/home"

ruff check .
mypy src
pytest -q
python -m safevault --help
python -m safevault --version
python -m safevault daemon run --test-once
python -m safevault tray --check
python - <<'PY'
from safevault import __version__

assert __version__ == "1.1.6"
print("version ok")
PY
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
    "safevault/ui/templates/storage.html",
    "safevault/ui/static/safevault.css",
    "safevault/ui/static/safevault.js",
    "safevault/ui/docs/README.zh-CN.md",
    "safevault/ui/docs/README.md",
    "safevault/ui/docs/INSTALL_EN.md",
    "safevault/ui/docs/INSTALL_ZH.md",
    "safevault/ui/docs/FAQ_EN.md",
    "safevault/ui/docs/FAQ_ZH.md",
    "safevault/ui/docs/USER_GUIDE_EN.md",
    "safevault/ui/docs/USER_GUIDE_ZH.md",
    "safevault/ui/docs/zh/GUI_GUIDE.md",
    "safevault/ui/docs/zh/RECOVERY_PLAYBOOK.md",
    "safevault/ui/docs/zh/CODEX_WORKFLOW.md",
    "safevault/ui/docs/zh/TROUBLESHOOTING.md",
    "safevault/ui/docs/zh/SAFETY_MODEL.md",
]
missing = [name for name in required if name not in names]
if missing:
    raise SystemExit(f"wheel missing GUI/doc assets: {missing}")
print("wheel assets ok")
PY
python -m twine check dist/*
