#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$PWD"
pid_file="${repo_root}/.data/dev.pid"

stop_tree() {
  local pid="$1"
  local child
  while IFS= read -r child; do
    if [[ "$child" =~ ^[0-9]+$ ]]; then stop_tree "$child"; fi
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill -TERM "$pid" 2>/dev/null || true
}

if [[ -f "$pid_file" ]]; then
  read -r dev_pid < "$pid_file" || true
  if [[ "${dev_pid:-}" =~ ^[0-9]+$ ]] && kill -0 "$dev_pid" 2>/dev/null; then
    command_line="$(ps -p "$dev_pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" != *"scripts/dev.sh"* ]]; then
      echo "The saved process ID no longer belongs to Class Notes. Check running apps before stopping Docker." >&2
      exit 1
    fi
    echo "Stopping Class Notes..."
    stop_tree "$dev_pid"
    for _ in {1..30}; do
      if ! kill -0 "$dev_pid" 2>/dev/null; then break; fi
      sleep 1
    done
    if kill -0 "$dev_pid" 2>/dev/null; then
      echo "Class Notes did not stop cleanly. Check the Start window." >&2
      exit 1
    fi
  fi
  rm -f "$pid_file"
  if curl --silent --fail http://127.0.0.1:3000 >/dev/null \
    || curl --silent --fail http://127.0.0.1:8000/readyz >/dev/null; then
    echo "A local app process is still running. Stop it before shutting down Docker." >&2
    exit 1
  fi
elif curl --silent --fail http://127.0.0.1:3000 >/dev/null \
  || curl --silent --fail http://127.0.0.1:8000/readyz >/dev/null; then
  echo "Class Notes was started outside the launcher. Stop it in its original terminal with Ctrl+C." >&2
  exit 1
fi

whisper_binary="${repo_root}/.venv-whisper-local/bin/whisper-local"
while IFS= read -r whisper_pid; do
  if [[ ! "$whisper_pid" =~ ^[0-9]+$ ]]; then continue; fi
  command_line="$(ps -p "$whisper_pid" -o command= 2>/dev/null || true)"
  if [[ "$command_line" == *"${whisper_binary} --serve --serve-host 127.0.0.1 --serve-port 7777"* ]]; then
    kill -TERM "$whisper_pid" 2>/dev/null || true
  fi
done < <(lsof -tiTCP:7777 -sTCP:LISTEN 2>/dev/null || true)

if docker info >/dev/null 2>&1; then
  docker compose down
fi
echo "Class Notes is stopped. Saved classes remain in the Docker volume."
