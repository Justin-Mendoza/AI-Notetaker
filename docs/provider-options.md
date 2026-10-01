# Transcription and summary providers

The default worker uses OpenAI `gpt-4o-transcribe` and `gpt-4o-mini`. For the personal Mac setup, it can use [drajb/whisper-local](https://github.com/drajb/whisper-local) for speech recognition and Kyma's Qwen 3.7 Flash for draft notes. Provider selection changes only the worker; the browser, private upload, queue, transcript, validation, and cleanup remain the same.

## Mac worker with Whisper Local and Kyma

1. On the Mac running the worker, install Python 3.11–3.13 and FFmpeg, then install Whisper Local in a separate environment. `soundfile` lets its API decode the MP3 chunks sent by this app:

   ```bash
   brew install ffmpeg
   python3.12 -m venv .venv-whisper-local
   .venv-whisper-local/bin/python -m pip install whisper-local==0.21.0 soundfile==0.14.0
   ./scripts/start-whisper-local.sh
   ```

   The first server start downloads the selected Whisper model into the user's Hugging Face cache. Keep that terminal open. The server listens only on `127.0.0.1:7777`; check `http://127.0.0.1:7777/health` before starting the worker.
2. Run this app's API and worker on the **same Mac**. Set these values in the root `.env`:

   ```dotenv
   STT_PROVIDER=whisper_local
   WHISPER_LOCAL_BASE_URL=http://127.0.0.1:7777/v1
   WHISPER_LOCAL_MODEL_LABEL=base
   SUMMARY_PROVIDER=kyma
   KYMA_API_KEY=your-server-only-key
   KYMA_BASE_URL=https://kymaapi.com/v1
   KYMA_SUMMARY_MODEL=qwen3.7-flash
   ```

3. Set `WHISPER_LOCAL_MODEL_LABEL` to the model actually selected in Whisper Local, so stored transcript metadata is accurate. Its local endpoint accepts `model=whisper-1` but runs the model selected in its own settings. Use a short non-sensitive meeting to check the transcript and Kyma's JSON schema response, then benchmark a 60-minute recording on the actual Mac.

The worker still downloads meeting audio from this app's private bucket to temporary disk. Whisper Local transcribes it on that Mac; the audio is not sent to a transcription API. **The transcript is sent to Kyma** for summary generation. Kyma is an API aggregator, so review its handling of meeting text before using sensitive recordings. Keep the Whisper Local server bound to loopback. It has no API authentication, and this app intentionally rejects a non-loopback URL.

Whisper Local is a desktop application for Windows and macOS. A hosted worker container cannot reach a Whisper Local server on your Mac by using `127.0.0.1`; that address would point inside the container. For a hosted worker, use the OpenAI STT provider until a private, authenticated local-worker connection is designed. Do not expose Whisper Local's unauthenticated server to the internet.

## Provider configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `STT_PROVIDER` | `openai` | `openai` or `whisper_local` |
| `STT_MODEL` | `gpt-4o-transcribe` | OpenAI transcription model |
| `WHISPER_LOCAL_BASE_URL` | `http://127.0.0.1:7777/v1` | Loopback endpoint used only for `whisper_local` |
| `WHISPER_LOCAL_MODEL_LABEL` | `base` | Metadata label; match Whisper Local's model setting |
| `SUMMARY_PROVIDER` | `openai` | `openai` or `kyma` |
| `SUMMARY_MODEL` | `gpt-4o-mini` | OpenAI Responses model |
| `KYMA_API_KEY` | unset | Server-only Kyma key |
| `KYMA_SUMMARY_MODEL` | `qwen3.7-flash` | Kyma chat model ID |

Kyma's Chat Completions endpoint uses `response_format` with `json_schema`. The app validates every response and evidence ID again before saving. The exact Qwen 3.7 Flash schema behavior through Kyma still needs a live credentialed smoke test; invalid or truncated output leaves the transcript available and makes the summary retryable.
