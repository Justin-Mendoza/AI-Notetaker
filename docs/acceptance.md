# Local Mac acceptance audit

Updated 2026-10-02. The original [design](design.md) described hosted meeting accounts; this version is a class-note app for one Mac. CI covers Python lint, formatting, API tests, PostgreSQL migrations, and web lint, type checking, and build. The 60-minute fixture test runs real FFmpeg with fake STT/LLM providers.

| Criterion | Evidence | Status |
| --- | --- | --- |
| Consent, record, upload, transcript and draft notes | Browser flow and API worker tests are implemented. A short real-provider browser recording is still needed. | Local smoke test required |
| 60-minute recording and ordered chunks | CI checks six ordered segments from a 60-minute fixture with real FFmpeg. | Automated check |
| Local-only access | API tests reject remote clients, unexpected Host, and cross-site writes; Compose binds data ports to loopback. | Automated check; inspect local ports |
| Refresh during processing | Status, transcript, and summary are persisted; browser polls the API. | Local smoke test required |
| Provider retry and failed-summary recovery | Worker tests cover backoff, saved segments, and summary retry without retranscription. | Automated check; real-provider smoke needed |
| Student-focused topic notes | Tests validate topic explanations and transcript evidence; a synthetic lesson produced topic notes through Kyma. Existing recordings can queue regeneration without retranscription. | Automated and synthetic provider checks; review a real class recording |
| Invalid media and recording failures | API validation, lease recovery, and browser error handling are implemented. | Automated check with manual browser cases |
| Delete and retention cleanup | Tests cover immediate unreadability, cascading row removal, and private file deletion. | Automated check; local retention smoke test needed |

Complete the [local smoke test](../deploy/README.md) before treating the app as ready for personal meetings. Kyma credentials and a review of its transcript handling remain prerequisites for sensitive meetings.
