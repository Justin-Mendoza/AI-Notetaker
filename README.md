# Meeting Notes

Private meeting notes app. This repository currently implements **Milestone 1** of [the design](docs/design.md): the Next.js shell, FastAPI meeting foundation, Supabase authentication, PostgreSQL migration, and local services. Recording, uploads, transcription, and summaries are later milestones.

## Requirements

- Node.js 20.19 or newer, npm, Python 3.11–3.14, Docker with the daemon running, and `ffprobe` from FFmpeg installed on the API host.
- A Supabase project using an **asymmetric JWT signing key**. This app verifies access tokens through the project's JWKS. Email sign-in must be enabled in Supabase Auth. Legacy HS256 projects need a different verification path and are not supported by this foundation.
- Create or invite the intended account in Supabase before signing in. The web app requests codes only for existing users; configure Supabase to prevent public signup for a private deployment.

## Local startup

1. Copy `.env.example` to `.env` and set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and matching `POSTGRES_PASSWORD`/`DATABASE_URL` values. Set fresh local bucket credentials there too. Never put server credentials in `apps/web/.env.local`.
2. Run `docker compose up -d`. MinIO is at `http://localhost:9001`; the init service creates the private `meeting-audio` bucket.
3. Run `python3 -m venv .venv && .venv/bin/pip install -e 'apps/api[dev]'`.
4. Run `.venv/bin/alembic -c apps/api/alembic.ini upgrade head`.
5. In one terminal run `.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --port 8000`.
6. Run `cd apps/web && npm install && cp .env.local.example .env.local && npm run dev`. Set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` in `.env.local` to the same Supabase project. Open `http://localhost:3000`.

Once dependencies and env files are set, `bash scripts/dev.sh` starts Compose, applies migrations, and launches the API and web dev servers together.

The frontend signs in with an emailed one-time code or link. Create or invite that user in Supabase first. From the library, select **New meeting**, confirm the consent reminder, and start recording. The browser uploads once after Stop and keeps the captured file available for retry while the tab stays open. The worker begins in Milestone 3, so uploads will remain queued in this branch.

`/healthz` checks the API process; `/readyz` checks database connectivity. FastAPI publishes OpenAPI at `/openapi.json` and an interactive API page at `/docs`. Every `/v1` route needs `Authorization: Bearer <Supabase access token>`.

After changing API response schemas, run `.venv/bin/python scripts/export_openapi.py` and then `cd apps/web && npm run api:types` to refresh the checked-in frontend types.

## Checks

```sh
.venv/bin/ruff check apps/api
.venv/bin/ruff format --check apps/api
.venv/bin/pytest apps/api/tests
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
cd apps/web && npm run lint && npm run typecheck && npm run build
```

The API tests use temporary SQLite databases and locally generated asymmetric test tokens. Run the migration against PostgreSQL from Compose as an additional integration check.

## Layout

- `apps/web`: Next.js App Router and Supabase sign-in shell.
- `apps/api/app`: FastAPI routes, auth, database, and models.
- `apps/api/alembic`: database migrations.
- `docs`: product design and API notes.
