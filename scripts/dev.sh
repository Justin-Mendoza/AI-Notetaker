#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$PWD"
if [[ ! -f .env ]]; then
  echo "Copy .env.example to .env and configure local credentials first." >&2
  exit 1
fi
if grep -q '^SUMMARY_PROVIDER=kyma$' .env && ! grep -Eq '^KYMA_API_KEY=[^[:space:]]+' .env; then
  echo "Add KYMA_API_KEY to .env before starting the app." >&2
  exit 1
fi
if grep -q '^KYMA_API_KEY=your-server-only-key$' .env; then
  echo "Replace the KYMA_API_KEY placeholder in .env." >&2
  exit 1
fi

umask 077
mkdir -p .data
chmod 700 .data
pid_file="${repo_root}/.data/dev.pid"
if [[ -f "$pid_file" ]]; then
  read -r prior_pid < "$pid_file" || true
  if [[ "${prior_pid:-}" =~ ^[0-9]+$ ]] && kill -0 "$prior_pid" 2>/dev/null; then
    prior_command="$(ps -p "$prior_pid" -o command= 2>/dev/null || true)"
    if [[ "$prior_command" == *"scripts/dev.sh"* ]]; then
      echo "Class Notes is already running (PID ${prior_pid})." >&2
      exit 1
    fi
  fi
fi
printf '%s\n' "$$" > "$pid_file"

pids=()
cleanup() {
  trap - EXIT INT TERM
  if (( ${#pids[@]} )); then
    for pid in "${pids[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
  if [[ -f "$pid_file" ]]; then
    read -r recorded_pid < "$pid_file" || true
    if [[ "${recorded_pid:-}" == "$$" ]]; then
      rm -f "$pid_file"
    fi
  fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM

docker compose up -d
.venv/bin/alembic -c apps/api/alembic.ini upgrade head

if [[ "$(sed -n 's/^STT_PROVIDER=//p' .env | tail -1)" == "whisper_local" ]] && ! curl --silent --fail http://127.0.0.1:7777/health >/dev/null; then
  ./scripts/start-whisper-local.sh &
  pids+=("$!")
  for attempt in {1..120}; do
    if curl --silent --fail http://127.0.0.1:7777/health >/dev/null; then break; fi
    if ! kill -0 "${pids[0]}" 2>/dev/null; then
      echo "Whisper Local failed to start." >&2
      exit 1
    fi
    sleep 1
  done
  if ! curl --silent --fail http://127.0.0.1:7777/health >/dev/null; then
    echo "Whisper Local did not become ready." >&2
    exit 1
  fi
fi

.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000 &
api_pid=$!
pids+=("$api_pid")
PYTHONPATH=apps/api .venv/bin/python -m app.worker.main &
worker_pid=$!
pids+=("$worker_pid")
(cd apps/web && exec node node_modules/next/dist/bin/next dev --hostname 127.0.0.1) &
web_pid=$!
pids+=("$web_pid")
wait "${pids[@]}"
