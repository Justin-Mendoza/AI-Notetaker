#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
whisper_local="${repo_root}/.venv-whisper-local/bin/whisper-local"

if [[ ! -x "${whisper_local}" ]]; then
  echo "Whisper Local is missing. Install it into .venv-whisper-local first." >&2
  exit 1
fi

exec "${whisper_local}" --serve --serve-host 127.0.0.1 --serve-port 7777
