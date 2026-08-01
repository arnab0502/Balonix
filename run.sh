#!/usr/bin/env bash
# TotalFootball launcher. Usage: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

if ! $PY -c "import fastapi, uvicorn, httpx" >/dev/null 2>&1; then
  echo "Installing dependencies..."
  $PY -m pip install -q -r requirements.txt
fi

HOST=$(grep -E '^TF_HOST=' .env 2>/dev/null | cut -d= -f2 || true)
PORT=$(grep -E '^TF_PORT=' .env 2>/dev/null | cut -d= -f2 || true)
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8000}

echo ""
echo "  TotalFootball  ->  http://${HOST}:${PORT}"
echo ""
exec $PY -m uvicorn server.main:app --host "$HOST" --port "$PORT" --reload
