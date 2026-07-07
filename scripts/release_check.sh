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
python -m twine check dist/*
