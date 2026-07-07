#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
export SAFEVAULT_HOME="$ROOT/home"
PROJECT="$ROOT/project"
mkdir -p "$PROJECT"

echo "hello" > "$PROJECT/a.txt"

python -m safevault init "$PROJECT"
python -m safevault snapshot "$PROJECT" --reason gui-smoke

PORT="${SAFEVAULT_GUI_SMOKE_PORT:-8765}"
TOKEN="test-token"
LOG="$ROOT/ui.log"

python -m safevault ui --host 127.0.0.1 --port "$PORT" --test-token "$TOKEN" > "$LOG" 2>&1 &
PID="$!"

cleanup() {
  kill "$PID" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/?token=$TOKEN" >/dev/null; then
    curl -fsS "http://127.0.0.1:$PORT/roots" --cookie "safevault_ui_token=$TOKEN" >/dev/null
    curl -fsS "http://127.0.0.1:$PORT/maintenance" --cookie "safevault_ui_token=$TOKEN" >/dev/null
    echo "GUI smoke test passed"
    exit 0
  fi
  sleep 0.5
done

cat "$LOG" >&2
echo "GUI smoke test failed" >&2
exit 1
