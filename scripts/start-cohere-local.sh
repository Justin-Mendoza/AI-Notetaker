#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv-cohere-speech/bin/python ]]; then
  echo "Cohere Local is missing. Follow docs/provider-options.md." >&2
  exit 1
fi
umask 077
export HF_HOME="$PWD/.data/cohere-cache"
export COHERE_LOCAL_MODEL="${COHERE_LOCAL_MODEL:-$(PYTHONPATH=apps/api .venv/bin/python -c 'from app.settings import settings; print(settings.cohere_local_model)')}"
export HF_HUB_OFFLINE=1
exec .venv-cohere-speech/bin/python -m uvicorn cohere_server:app --app-dir scripts --host 127.0.0.1 --port 7778
