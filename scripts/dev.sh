#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose up -d
.venv/bin/alembic -c apps/api/alembic.ini upgrade head

.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --port 8000 &
api_pid=$!
PYTHONPATH=apps/api .venv/bin/python -m app.worker.main &
worker_pid=$!
(cd apps/web && npm run dev) &
web_pid=$!

cleanup() {
  kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait "$api_pid" "$worker_pid" "$web_pid"
