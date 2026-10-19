# Afterclass — your class study assistant

**Stay with the lesson. Come back ready to study.** Afterclass is a personal study assistant for lectures you choose to record. It creates a transcript as class goes on, then turns the completed transcript into organized notes you can revisit: topics explained, important details, quick review points, assignments, and questions to follow up on.

Afterclass runs locally on one Mac. Audio is transcribed on your Mac with Cohere; after recording, the transcript is sent to DeepSeek through Kyma to draft study notes. Notes are a starting point for review, so check them against the transcript. See [how audio and transcripts are processed](docs/provider-options.md).

## How it helps you study

- **Stay present:** record a class you choose to capture instead of trying to write down every sentence.
- **Follow along:** see transcript sections appear during class, with a short delay.
- **Review the lesson:** get topic explanations, key details, quick review points, assignments, and questions after you stop.
- **Return to the source:** use approximate time links in the notes to find the related transcript section.
- **Keep your materials:** your class recordings, transcripts, and notes stay in your local app; copy or download notes and transcripts for your own study routine.

Afterclass is a personal, single-user Mac app, not a hosted service or a substitute for attending class. Recording is opt-in; follow your instructor’s guidance and your school’s rules. Processing classroom speech with AI may require permission.

## Requirements

- Node.js 20.19 or newer, npm, Python 3.11–3.14, Docker with the daemon running, and FFmpeg (`ffmpeg` and `ffprobe`) installed for the API and worker.
- Cohere Local installed on this Mac using [the provider instructions](docs/provider-options.md), and a Kyma API key for summaries.

## Local startup

For this Mac, double-click [Start Class Notes.command](Start%20Class%20Notes.command) in Finder. The launcher starts Docker Desktop if needed, starts Afterclass’s local services, and opens the app. Keep its Terminal window open while using Afterclass. Double-click [Stop Class Notes.command](Stop%20Class%20Notes.command) to stop the services and PostgreSQL. Your saved classes remain in the named Docker volume; do not use `docker compose down -v` unless you intend to erase that database.

1. Copy `.env.example` to `.env`. Set matching `POSTGRES_PASSWORD`/`DATABASE_URL` values and `KYMA_API_KEY`. Keep provider credentials out of `apps/web/.env.local`. Recordings are stored under the ignored `.data/recordings` directory with owner-only file permissions; set `LOCAL_RECORDING_DIR` to an absolute path if you want them elsewhere.
2. Run `docker compose up -d` to start PostgreSQL on loopback.
3. Run `python3 -m venv .venv && .venv/bin/pip install -e 'apps/api[dev]'`.
4. Run `.venv/bin/alembic -c apps/api/alembic.ini upgrade head`.
5. Start Cohere Local with `./scripts/start-cohere-local.sh`. In another terminal run `.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000`. In another run `PYTHONPATH=apps/api .venv/bin/python -m app.worker.main` with the same `.env`.
6. Run `cd apps/web && npm install && npm run dev -- --hostname 127.0.0.1`. Open `http://localhost:3000` on this Mac.

Once dependencies and env files are set, `bash scripts/dev.sh` starts PostgreSQL, applies migrations, starts Cohere Local if needed, and launches the API, worker, and web app together. It checks that `KYMA_API_KEY` is set before starting.

The worker runs cleanup at startup and hourly to purge expired raw audio, remove deleted meetings and abandoned drafts, and sweep old recording files. You can also run `PYTHONPATH=apps/api .venv/bin/python -m app.worker.cleanup` manually. Local operation and smoke-test steps are in [deploy/README.md](deploy/README.md).

To make a study set, choose **Record a class**, name the lesson, review the consent reminder, and start recording. Afterclass supports up to two hours per recording (100 MB maximum). It saves audio in your browser when storage is available and transcribes complete one-minute sections on your Mac. Transcription appears with a delay; it is not word-by-word streaming. After you stop, the app fills any missing sections and sends the completed transcript to DeepSeek through Kyma to draft study notes. Each topic includes an explanation, key details, and approximate links back to the transcript. You can copy or download notes as Markdown and download the transcript as text. Existing transcripts can generate a fresh set of notes.

Keep the Mac awake, lid open, and plugged in during class. If the tab closes or crashes, reopen **Record a class** in the same browser to recover audio already saved there; recording does not continue during an interruption. Avoid private browsing, which may not retain backups. If note generation fails, your transcript and previous notes remain available to retry.

For non-sensitive local audio, run `bash scripts/generate_fixture.sh 120 /private/tmp/meeting-short.mp3`. Use `7200` for a two-hour file above the speech API's per-file limit. The worker submits only compressed chunks below 20 MB.

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

The API tests use temporary SQLite databases and test local-only access rules. CI runs the migration against PostgreSQL. Before relying on it for class, make a short recording with your actual microphone and confirm the transcript and notes are usable. Synthetic tests do not establish classroom accuracy.

## Layout

- `apps/web`: Next.js App Router and recording interface.
- `apps/api/app`: FastAPI routes, local access control, database, and models.
- `apps/api/alembic`: database migrations.
- `docs`: product design and API notes.

## Before a long class

Before class, open `http://localhost:3000` and make a short test with the microphone you plan to use. Check that the transcript captures speech clearly and that the notes help you review it. Place the microphone where your instructor is clearly audible. Keep the Mac plugged in and awake, with its lid open; leave the recording tab and startup Terminal window open. The limit is two hours or 100 MB. After class, wait for upload to finish before closing the tab. Transcription and note generation continue afterward; Kyma needs internet to prepare notes. **Retry** resumes failed note generation without retranscribing completed sections. Download the notes or transcript if you want to use them in your own study workflow.
