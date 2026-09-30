# Milestone 1 API

All `/v1` routes require a Supabase access token. Unauthorized requests receive `401`; another user's meeting returns `404`. Errors use `{ "error": { "code", "message", "request_id" } }`. Responses carry `X-Request-ID`.

| Route | Purpose |
| --- | --- |
| `POST /v1/meetings` | Create a draft after affirmative consent. |
| `GET /v1/meetings?limit=&cursor=` | List owned meetings newest first. |
| `GET /v1/meetings/{id}` | Get an owned meeting and foundation status flags. |
| `PATCH /v1/meetings/{id}` | Rename an owned meeting. |
| `POST /v1/meetings/{id}/recording` | Multipart `file` and `duration_ms`, plus `Idempotency-Key`; validates and stores one private recording, then queues a job. |
| `GET /healthz` | Process health. |
| `GET /readyz` | Database readiness. |

Transcript, summary, retry, and delete routes arrive in later milestones.
