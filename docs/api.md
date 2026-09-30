# Meeting Notes API

All `/v1` routes require a Supabase access token. Unauthorized requests receive `401`; another user's meeting returns `404`. Errors use `{ "error": { "code", "message", "request_id" } }`. Responses carry `X-Request-ID`.

| Route | Purpose |
| --- | --- |
| `POST /v1/meetings` | Create a draft after affirmative consent. |
| `GET /v1/meetings?limit=&cursor=` | List owned meetings newest first. |
| `GET /v1/meetings/{id}` | Get an owned meeting and foundation status flags. |
| `PATCH /v1/meetings/{id}` | Rename an owned meeting. |
| `POST /v1/meetings/{id}/recording` | Multipart `file` and `duration_ms`, plus `Idempotency-Key`; validates and stores one private recording, then queues a job. |
| `GET /v1/meetings/{id}/transcript` | Ordered approximate chunk ranges and full text once transcription completes. |
| `GET /v1/meetings/{id}/summary` | Validated structured draft, available only when ready. |
| `POST /v1/meetings/{id}/retry` | Requeue a failed transient job without duplicating saved segments. |
| `GET /healthz` | Process health. |
| `GET /readyz` | Database readiness. |

Deletion and retention cleanup arrive in the hardening milestone.
