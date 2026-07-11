#!/usr/bin/env bash
# Launch the Eden Archive admin app. Local only, bound to loopback.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="admin/.venv"
REQS="admin/requirements.txt"
STAMP="$VENV/.reqs-sha"
PORT="${PORT:-8765}"

# Prefer a Python that reliably has wheels for everything we need.
PY=""
for candidate in python3.12 python3.13 python3.14 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "error: no python3 found on PATH" >&2
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "[admin] creating venv with $PY ($($PY -V 2>&1))"
  "$PY" -m venv "$VENV"
fi

# Reinstall only when requirements.txt actually changed.
WANT="$(shasum -a 256 "$REQS" | cut -d' ' -f1)"
HAVE="$(cat "$STAMP" 2>/dev/null || true)"
if [ "$WANT" != "$HAVE" ]; then
  echo "[admin] installing dependencies"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$REQS"
  echo "$WANT" > "$STAMP"
fi

if [ ! -f node-mapgen/dist/generate-map.js ]; then
  echo "[admin] warning: node-mapgen/dist not built — map generation will be unavailable."
  echo "[admin]          fix with: cd node-mapgen && npm install && npx tsc"
fi

exec "$VENV/bin/uvicorn" admin.app.main:app \
  --host 127.0.0.1 --port "$PORT" --reload \
  --reload-dir admin
