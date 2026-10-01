# MVP acceptance audit

Audit date: 2026-09-30. The review covers the MVP in [design.md](design.md), excluding Phase 2 and Phase 3. CI runs Python lint, formatting, API tests, PostgreSQL migrations, and web lint, type checking, and build. The 60-minute fixture test uses real FFmpeg and fake STT/LLM providers in CI.

| Release criterion | Evidence | Status |
| --- | --- | --- |
| Sign in, consent, record, upload, ready transcript and draft notes | Browser and API flow implemented; API worker tests cover transcription to ready. Real Supabase and microphone flow needs hosted smoke test. | Hosted check required |
| 60-minute recording, per-file STT limit, chunk order | CI generates a 60-minute MP3 above 25 MB, runs real FFmpeg splitting through worker with fake providers, and checks six ordered segments and ready status. | Automated check |
| Second account denied list, fetch, retry, delete, and private object access | Owner isolation tests cover API reads and mutations; object keys are not returned. Direct bucket access needs a deployed private-bucket check. | Hosted bucket check required |
| Refresh while processing | Status, transcript, and summary are persisted and fetched through polling endpoints; deployed browser refresh needs smoke test. | Hosted check required |
| STT/LLM 429 and 5xx backoff, terminal failure | Provider adapters map transient errors; worker retry and failure state tests cover idempotence and saved segments. Real provider responses need hosted fault/smoke validation. | Automated check with hosted provider prerequisite |
| Summary failure keeps transcript; retry avoids STT | Transcript endpoint uses completed transcription stage; worker summary retry test checks no new STT calls. | Automated check |
| Invalid media, mic errors, size/duration, interrupted upload, worker restart | API validation and lease-reclaim tests pass; browser has actionable errors and in-memory retry. Manual browser/device cases need smoke test. | Automated check with hosted browser prerequisite |
| Delete denies reads and removes rows/audio; retention purges | API delete and idempotent cleanup tests cover immediate 404, cascading row removal, and object delete calls. Managed bucket verification and scheduled cleanup need hosted smoke test. | Automated check with hosted storage prerequisite |
| CI gates and real-provider smoke test | CI workflow covers code checks, PostgreSQL migration, and fake-provider integration. [Deployment guide](../deploy/README.md) gives exact hosted smoke steps. | Hosted check required |

## Deployment prerequisites

Supply a Supabase project with asymmetric JWT signing and two invited accounts; managed PostgreSQL; a private S3-compatible bucket; OpenAI credentials and approved data handling; HTTPS web/API domains; a scheduled cleanup process; backup retention and budget alerts. Run Alembic before service rollout. Complete the hosted smoke test in [deploy/README.md](../deploy/README.md) before calling the MVP release accepted.
