# Local Mac operation

This version is for one Mac. Do not deploy its API or web app to a public host: there is no account sign-in. The API checks loopback clients, local Host values, and the configured browser Origin; PostgreSQL is bound to loopback by Compose. Raw recordings are private files under `.data/recordings` by default. Follow the [startup guide](../README.md).

Run `alembic -c apps/api/alembic.ini upgrade head` before starting the API and worker. Run `PYTHONPATH=apps/api .venv/bin/python -m app.worker.cleanup` hourly to delete expired raw audio, removed meetings, abandoned drafts, and orphaned objects. A macOS launch agent or other local scheduler can invoke it. `/internal/metrics` is available only when `METRICS_TOKEN` is set; keep that token out of the web app.

## Local smoke test

1. Start Docker Compose, Whisper Local, the API, worker, and web app using the README. Confirm `http://localhost:8000/readyz` and `http://127.0.0.1:7777/health` respond.
2. Open `http://localhost:3000` on the Mac. Confirm consent, record a short non-sensitive meeting, stop, and wait for `ready`. Check transcript, draft notes, title rename, copy, and transcript download. Refresh while processing to confirm status persists.
3. Confirm an API request from a non-loopback client and a write with an unrelated Origin receive `403`. Check that recording files are owner-readable only.
4. Process a 60-minute non-sensitive fixture and verify ordered transcript chunks without gaps or duplicates. See `scripts/generate_fixture.sh`.
5. Delete the meetings, run cleanup, and verify their rows and audio objects are gone. Set a test recording's `purge_after` in the past, run cleanup, and verify raw audio is removed.

A hosted or network-accessible version requires a new authentication and network-security design before deployment.
