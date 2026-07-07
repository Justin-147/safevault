#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
export SAFEVAULT_HOME="$ROOT/home"
PROJECT="$ROOT/project"
mkdir -p "$PROJECT"

echo "v1" > "$PROJECT/a.txt"
python -m safevault init "$PROJECT"
python -m safevault snapshot "$PROJECT" --reason initial

echo "v2" > "$PROJECT/a.txt"
python -m safevault snapshot "$PROJECT" --reason second
rm "$PROJECT/a.txt"
python -m safevault snapshot "$PROJECT" --reason after-delete
python -m safevault restore "$PROJECT/a.txt" --latest
test "$(cat "$PROJECT/a.txt")" = "v2"

echo "important" > "$PROJECT/important.txt"
python -m safevault run --project "$PROJECT" -- python -c "from pathlib import Path; Path('important.txt').unlink(); Path('new.txt').write_text('new')"
SANDBOX_ID="$(python -m safevault sandboxes --latest --json | python -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")"
python -m safevault apply "$SANDBOX_ID" --dry-run
python -m safevault apply "$SANDBOX_ID"
test -f "$PROJECT/important.txt"
test -f "$PROJECT/new.txt"

python -m safevault verify --deep
python -m safevault doctor --deep
