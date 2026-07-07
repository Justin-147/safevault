#!/usr/bin/env bash
set -euo pipefail

ruff check .
mypy src
pytest -q
python -m safevault --help
bash scripts/smoke.sh
python -m build
python -m twine check dist/*
