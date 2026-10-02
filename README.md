# Class Notes

Private, single-owner class notes app for one Mac. The app records microphone audio after explicit consent, uploads it to private local storage, processes it in a separate worker, and saves a transcript and reviewable study notes.

The supplied `.env.example` selects [Whisper Local for transcription and Qwen through Kyma for summaries](docs/provider-options.md). Model and provider settings remain configurable. Audio stays on this Mac for transcription; the transcript goes to Kyma for summaries.

## Requirements

- Node.js 20.19 or newer, npm, Python 3.11–3.14, Docker with the daemon running, and FFmpeg (`ffmpeg` and `ffprobe`) installed for the API and worker.
- Whisper Local installed on this Mac using [the provider instructions](docs/provider-options.md), and a Kyma API key for summaries.

## Local startup

For this Mac, double-click [Start Class Notes.command](Start%20Class%20Notes.command) in Finder. It starts Docker Desktop if needed, starts the local services, and opens the web app. Keep its Terminal window open while using the app. Double-click [Stop Class Notes.command](Stop%20Class%20Notes.command) to stop the services and PostgreSQL. Your saved classes remain in the named Docker volume; do not use `docker compose down -v` unless you intend to erase that database.

1. Copy `.env.example` to `.env`. Set matching `POSTGRES_PASSWORD`/`DATABASE_URL` values and `KYMA_API_KEY`. Keep provider credentials out of `apps/web/.env.local`. Recordings are stored under the ignored `.data/recordings` directory with owner-only file permissions; set `LOCAL_RECORDING_DIR` to an absolute path if you want them elsewhere.
2. Run `docker compose up -d` to start PostgreSQL on loopback.
3. Run `python3 -m venv .venv && .venv/bin/pip install -e 'apps/api[dev]'`.
4. Run `.venv/bin/alembic -c apps/api/alembic.ini upgrade head`.
5. Start Whisper Local with `./scripts/start-whisper-local.sh`. In another terminal run `.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000`. In another run `PYTHONPATH=apps/api .venv/bin/python -m app.worker.main` with the same `.env`.
6. Run `cd apps/web && npm install && npm run dev -- --hostname 127.0.0.1`. Open `http://localhost:3000` on this Mac.

Once dependencies and env files are set, `bash scripts/dev.sh` starts PostgreSQL, applies migrations, starts Whisper Local if needed, and launches the API, worker, and web app together. It checks that `KYMA_API_KEY` is set before starting.

The worker runs cleanup at startup and hourly to purge expired raw audio, remove deleted meetings and abandoned drafts, and sweep old recording files. You can also run `PYTHONPATH=apps/api .venv/bin/python -m app.worker.cleanup` manually. Local operation and smoke-test steps are in [deploy/README.md](deploy/README.md).

From the library, select **Record a class**, confirm the consent reminder, and start recording. The browser uploads once after Stop and keeps the captured file available for retry while the tab stays open. The worker transcribes approximate ten-minute chunks and saves the transcript, then produces schema-validated study notes. Each topic has a heading, a short explanation, key details, and links to approximate transcript times. The page also includes a quick review, explicit assignments, and questions to revisit. You can copy or download the notes as Markdown and download the transcript as text. Existing recordings can regenerate notes from their saved transcripts. If summarization fails, the transcript and any previous notes remain available for retry.

For non-sensitive local audio, run `bash scripts/generate_fixture.sh 120 /private/tmp/meeting-short.mp3`. Use `3600` for a 60-minute file above the speech API's per-file limit. The worker submits only compressed chunks below 20 MB.

`/healthz` checks the API process; `/readyz` checks database connectivity. FastAPI publishes OpenAPI at `/openapi.json` and an interactive API page at `/docs`. `/v1` routes accept only loopback clients using `localhost` or `127.0.0.1` as the API host. Browser requests may come from `localhost`, `127.0.0.1`, or `[::1]` on the port set by `ALLOWED_WEB_ORIGIN`; write requests require one of those `Origin` headers. Run the web app, API, and PostgreSQL bound to loopback. Anyone with access to the local OS account or local processes may be able to access the app; this is a personal Mac setup, not a network service.

After changing API response schemas, run `.venv/bin/python scripts/export_openapi.py` and then `cd apps/web && npm run api:types` to refresh the checked-in frontend types.

## Checks

```sh
.venv/bin/ruff check apps/api
.venv/bin/ruff format --check apps/api
.venv/bin/pytest apps/api/tests
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
cd apps/web && npm run lint && npm run typecheck && npm run build
```

The API tests use temporary SQLite databases and test local-only access rules. CI runs the migration against PostgreSQL. A real-provider smoke test still needs local storage, FFmpeg, Whisper Local, and a Kyma key.

## Layout

- `apps/web`: Next.js App Router and recording interface.
- `apps/api/app`: FastAPI routes, local access control, database, and models.
- `apps/api/alembic`: database migrations.
- `docs`: product design and API notes.
