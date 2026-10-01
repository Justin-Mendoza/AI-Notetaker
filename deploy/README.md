# Hosted MVP deployment

Deploy `apps/web` as a Next.js application. Build `apps/api/Dockerfile` once and run the same image as two always-on services:

| Service | Command | Exposure |
| --- | --- | --- |
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | HTTPS reverse proxy; allow uploads up to 101 MB and a generous upload timeout |
| Worker | `python -m app.worker.main` | Private only; one replica initially |

Both services need `DATABASE_URL`, Supabase auth settings, private bucket settings, `OPENAI_API_KEY`, and configurable model IDs. The worker image includes FFmpeg. Set `ALLOWED_WEB_ORIGIN` to the exact web origin. Put the API, worker, database, and bucket in the same region where possible. Use separate credentials and buckets for staging and production. Keep all server secrets out of the Next.js public environment.

The default container deployment uses OpenAI providers. The optional [Whisper Local + Kyma setup](../docs/provider-options.md) runs the worker on the same Mac as Whisper Local; a hosted container cannot reach that Mac's loopback API.

Run `alembic -c apps/api/alembic.ini upgrade head` using the API image as a release step **before** rolling out either service. Check `/readyz` and worker startup logs. Schedule `python -m app.worker.cleanup` hourly with the same image and secrets. Alert on failed jobs, overdue raw audio, and nonzero cleanup errors. `/internal/metrics` provides the current job counts and overdue-audio count to a private monitor when `METRICS_TOKEN` is set; do not expose the token in the web app.

Configure a private bucket with no public-read policy. Use TLS for web, API, and object storage endpoints. Set a budget alert and provider rate limits. Document database backup retention and review transcription/LLM provider handling before accepting sensitive meetings or launching publicly.

## Hosted smoke test

1. Invite two test accounts in Supabase and disable public signups. Confirm one can sign in on the deployed HTTPS URL.
2. Record a short consented test meeting, wait for `ready`, and verify ordered transcript, draft notes, title rename, copy, and transcript download. Refresh while processing and verify status persists.
3. Sign in as account two and confirm the first account's meeting URL and retry/delete requests return 404. Confirm direct anonymous bucket access is denied.
4. Upload a 60-minute non-sensitive fixture through the authenticated API, then verify all expected transcript chunks are present exactly once and a summary is saved. See `scripts/generate_fixture.sh`.
5. Delete both meetings; verify API reads fail immediately, run the cleanup command, and verify object and rows are gone. Set a test recording's `purge_after` into the past, run cleanup, and verify its raw object is removed.

These provider, auth, storage, FFmpeg, and hosted browser steps require deployed credentials and services; local fake-provider tests cover the state transitions without spending provider credits.
