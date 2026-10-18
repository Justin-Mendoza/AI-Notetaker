#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
umask 077
mkdir -p .data
chmod 700 .data

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is required. Install it, then try again." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker
  for _ in {1..120}; do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
  done
  if ! docker info >/dev/null 2>&1; then
    echo "Docker Desktop did not become ready. Open it and try again." >&2
    exit 1
  fi
fi

if curl --silent --fail http://127.0.0.1:3000 >/dev/null \
  && curl --silent --fail http://127.0.0.1:8000/readyz >/dev/null; then
  echo "Class Notes is already running."
  open http://localhost:3000
  exit 0
fi

dev_pid=""
own_process=false
if [[ -f .data/dev.pid ]]; then
  read -r prior_pid < .data/dev.pid || true
  if [[ "${prior_pid:-}" =~ ^[0-9]+$ ]] && kill -0 "$prior_pid" 2>/dev/null; then
    prior_command="$(ps -p "$prior_pid" -o command= 2>/dev/null || true)"
    if [[ "$prior_command" == *"scripts/dev.sh"* ]]; then
      dev_pid="$prior_pid"
      echo "Class Notes is already starting..."
    fi
  fi
fi
if [[ -z "$dev_pid" ]]; then
  bash scripts/dev.sh &
  dev_pid=$!
  own_process=true
  trap 'kill -TERM "$dev_pid" 2>/dev/null || true' EXIT INT TERM
  echo "Starting Class Notes..."
fi
for _ in {1..120}; do
  if ! kill -0 "$dev_pid" 2>/dev/null; then
    echo "Class Notes could not start. See the messages above in this window." >&2
    exit 1
  fi
  if curl --silent --fail http://127.0.0.1:3000 >/dev/null \
    && curl --silent --fail http://127.0.0.1:8000/readyz >/dev/null; then
    echo "Class Notes is ready."
    open http://localhost:3000
    if [[ "$own_process" == true ]]; then
      echo "Keep this window open while using the app, or use Stop Class Notes.command."
      wait "$dev_pid"
    fi
    exit 0
  fi
  sleep 1
done

echo "Class Notes did not become ready. See the messages above in this window." >&2
exit 1
