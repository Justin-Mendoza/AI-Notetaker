# Transcription and summary providers

## Current Mac setup: Cohere Transcribe locally

The Mac setup uses **Cohere Transcribe 03-2026**, via MLX on Apple Silicon, with the community `mlx-community/cohere-transcribe-03-2026-mlx-8bit` conversion. This is a quantized conversion, not an official Cohere-hosted endpoint. Audio is processed on the Mac. DeepSeek v4.1 Flash through Kyma receives the resulting transcript to create study notes.

A separate `.venv-cohere-speech` keeps MLX dependencies out of the API environment:

```bash
uv venv --python python3.14 .venv-cohere-speech
uv pip install --python .venv-cohere-speech/bin/python -r scripts/cohere-requirements.txt
HF_HOME="$PWD/.data/cohere-cache" .venv-cohere-speech/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("mlx-community/cohere-transcribe-03-2026-mlx-8bit", allow_patterns=["mlx-int8/*"], local_dir=".data/cohere-model"); snapshot_download("mlx-community/silero-vad", allow_patterns=["*.json", "*.safetensors"])'
```

The downloads must finish before offline use. The ASR model loads with strict checkpoint validation from `.data/cohere-model/mlx-int8` using `mlx-speech`; MLX Audio supplies only the Silero voice detector. The launcher sets `HF_HUB_OFFLINE=1` for transcription. It loads the model once, binds only to `127.0.0.1:7778`, serializes requests, and processes one short model window at a time to bound GPU memory. Local voice activity detection skips silence. English is the default language; `COHERE_LOCAL_LANGUAGE` can override it when launching the service. Do not expose this local service to the network.

Root `.env` configuration:

```dotenv
STT_PROVIDER=cohere_local
COHERE_LOCAL_BASE_URL=http://127.0.0.1:7778/v1
COHERE_LOCAL_MODEL=mlx-community/cohere-transcribe-03-2026-mlx-8bit
SUMMARY_PROVIDER=kyma
KYMA_BASE_URL=https://kymaapi.com/v1
KYMA_SUMMARY_MODEL=deepseek-v4.1-flash
```

Keep `KYMA_API_KEY` server-side in `.env`. A GitHub Actions secret is separate from the app's local credentials. The Start Class Notes launcher starts the database, Cohere service, API, worker, and web app. The health endpoint returns the loaded model at `http://127.0.0.1:7778/health`.

During class, complete one-minute transcript windows are saved and shown in the recorder. The browser sends a growing audio prefix to the local API so container headers are preserved; the API extracts only the next complete minute for Cohere. These requests stay on loopback. They are serialized and time-limited; a live failure does not stop recording. After Stop, the worker reuses saved minutes and fills gaps and the last partial minute from the full recording. Older recordings use ten-minute recovery chunks. Cohere divides audio into short inference windows. DeepSeek receives the complete transcript after recording ends. A two-hour class is supported, subject to the 100 MB upload limit. Capture requests 64 kbps audio (about 58 MB for two hours, excluding container overhead; browsers may choose a different bitrate).

Keep the Mac awake and the browser tab open throughout recording and upload. Browser backups recover saved chunks on the same browser and origin; private mode, browser storage removal, and disk failures can prevent recovery. Recording cannot continue while the Mac sleeps or the page is closed. Before class, make a short recording with the actual microphone and check both the transcript and notes. Synthetic tests do not establish classroom accuracy or processing time.

Sources: [Cohere model card](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026), [MLX Audio Cohere implementation](https://github.com/Blaizzy/mlx-audio/tree/main/mlx_audio/stt/models/cohere_asr).

## Other supported providers

OpenAI transcription remains available with `STT_PROVIDER=openai`, `OPENAI_API_KEY`, and `STT_MODEL`. Whisper Local remains available with `STT_PROVIDER=whisper_local`, `WHISPER_LOCAL_BASE_URL=http://127.0.0.1:7777/v1`, and `WHISPER_LOCAL_MODEL_LABEL=base`; start it with `scripts/start-whisper-local.sh`.

Summaries use `SUMMARY_PROVIDER=kyma` or `openai`. Kyma responses are schema-validated with transcript evidence IDs. Failed summarization retains the transcript and existing notes so generation can be retried.
