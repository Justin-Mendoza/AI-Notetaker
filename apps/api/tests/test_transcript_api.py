import uuid

from app.db.session import get_db
from app.main import app
from app.models.job import ProcessingJob
from app.models.meeting import Meeting, utc_now
from app.models.summary import Summary
from app.models.transcript import TranscriptSegment


def db_for_client():
    generator = app.dependency_overrides[get_db]()
    return generator, next(generator)


def test_transcript_is_ordered_and_owner_scoped(api_client):
    client, identity = api_client
    response = client.post(
        "/v1/meetings", json={"consent_confirmed": True, "consent_policy_version": "v1"}
    )
    meeting_id = uuid.UUID(response.json()["meeting"]["id"])
    generator, db = db_for_client()
    now = utc_now()
    db.add(
        ProcessingJob(
            meeting_id=meeting_id,
            kind="process_recording",
            stage="summarizing",
            status="completed",
            cursor=2,
            attempts=1,
            max_attempts=3,
            run_after=now,
            created_at=now,
            updated_at=now,
        )
    )
    for number, text in [(1, "second"), (0, "first")]:
        db.add(
            TranscriptSegment(
                meeting_id=meeting_id,
                sequence_no=number,
                start_ms=number * 1000,
                end_ms=(number + 1) * 1000,
                text=text,
                provider="fake",
                model="fake-v1",
                created_at=now,
            )
        )
    db.commit()
    generator.close()

    transcript = client.get(f"/v1/meetings/{meeting_id}/transcript")
    assert transcript.status_code == 200
    assert transcript.json()["full_text"] == "first\nsecond"
    assert [item["sequence_no"] for item in transcript.json()["segments"]] == [0, 1]
    assert client.get(f"/v1/meetings/{meeting_id}").json()["has_transcript"] is True
    identity["owner"] = uuid.uuid4()
    assert client.get(f"/v1/meetings/{meeting_id}/transcript").status_code == 404


def test_failed_job_retry_is_owner_scoped(api_client):
    client, identity = api_client
    owner = identity["owner"]
    response = client.post(
        "/v1/meetings", json={"consent_confirmed": True, "consent_policy_version": "v1"}
    )
    meeting_id = uuid.UUID(response.json()["meeting"]["id"])
    generator, db = db_for_client()
    meeting = db.get(Meeting, meeting_id)
    meeting.status = "failed"
    now = utc_now()
    db.add(
        ProcessingJob(
            meeting_id=meeting_id,
            kind="process_recording",
            stage="transcribing",
            status="failed",
            cursor=0,
            attempts=3,
            max_attempts=3,
            run_after=now,
            last_error_code="STT_TEMPORARY",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    generator.close()
    identity["owner"] = uuid.uuid4()
    assert client.post(f"/v1/meetings/{meeting_id}/retry").status_code == 404
    identity["owner"] = owner
    retried = client.post(f"/v1/meetings/{meeting_id}/retry")
    assert retried.status_code == 202
    assert retried.json() == {"status": "queued"}
    assert client.post(f"/v1/meetings/{meeting_id}/retry").status_code == 409


def test_summary_is_hidden_until_ready_and_owner_scoped(api_client):
    client, identity = api_client
    response = client.post(
        "/v1/meetings", json={"consent_confirmed": True, "consent_policy_version": "v1"}
    )
    meeting_id = uuid.UUID(response.json()["meeting"]["id"])
    assert client.get(f"/v1/meetings/{meeting_id}/summary").status_code == 404
    generator, db = db_for_client()
    now = utc_now()
    db.add(
        Summary(
            meeting_id=meeting_id,
            schema_version="v1",
            prompt_version="v1",
            model="fake",
            content_json={
                "overview": "Planning was discussed.",
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "open_questions": [],
            },
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    generator.close()
    assert client.get(f"/v1/meetings/{meeting_id}/summary").status_code == 404
    generator, db = db_for_client()
    meeting = db.get(Meeting, meeting_id)
    meeting.status = "ready"
    db.commit()
    generator.close()
    summary_response = client.get(f"/v1/meetings/{meeting_id}/summary")
    assert summary_response.json()["summary"]["overview"] == "Planning was discussed."
    identity["owner"] = uuid.uuid4()
    assert client.get(f"/v1/meetings/{meeting_id}/summary").status_code == 404
