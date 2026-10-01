# Meeting Notes API

All `/v1` routes are for the single owner on this Mac. The API accepts loopback clients and local Host values only. Browser requests use the configured web origin; writes require its `Origin` header. Rejected remote or cross-site requests receive `403`. Errors use `{ "error": { "code", "message", "request_id" } }`. Responses carry `X-Request-ID`.

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
| `DELETE /v1/meetings/{id}` | Deny reads immediately and queue permanent private data cleanup. |
| `GET /healthz` | Process health. |
| `GET /readyz` | Database readiness. |

Upload requests are bounded at 101 MB including multipart framing; audio itself is limited to 100 MB and 90 minutes. Per-owner meeting and upload rates and per-job manual retries can be configured through the server environment. The private `/internal/metrics` endpoint requires `METRICS_TOKEN` and reports job counts and overdue raw audio.
