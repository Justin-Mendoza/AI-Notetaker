import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.job import ProcessingJob
from app.models.meeting import Meeting, utc_now
from app.models.recording import Recording
from app.models.summary import Summary
from app.models.transcript import TranscriptSegment
from app.worker.cleanup import cleanup_once, purge_expired_audio


class FakeStorage:
    def __init__(self):
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)

    def list_objects(self):
        return iter([])


def test_delete_denies_future_owner_reads_immediately(api_client):
    client, identity = api_client
    owner = identity["owner"]
    response = client.post(
        "/v1/meetings", json={"consent_confirmed": True, "consent_policy_version": "v1"}
    )
    meeting_id = response.json()["meeting"]["id"]
    identity["owner"] = uuid.uuid4()
    assert client.delete(f"/v1/meetings/{meeting_id}").status_code == 404
    identity["owner"] = owner
    assert client.delete(f"/v1/meetings/{meeting_id}").status_code == 204
    assert client.get("/v1/meetings").json()["items"] == []
    assert client.get(f"/v1/meetings/{meeting_id}").status_code == 404
    assert client.patch(f"/v1/meetings/{meeting_id}", json={"title": "Return"}).status_code == 404
    assert client.post(f"/v1/meetings/{meeting_id}/retry").status_code == 404
    assert client.delete(f"/v1/meetings/{meeting_id}").status_code == 404


def test_cleanup_removes_deleted_meeting_and_audio_idempotently():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    meeting_id = uuid.uuid4()
    segment_id = uuid.uuid4()
    now = utc_now()
    key = f"{uuid.uuid4()}/{meeting_id}/{uuid.uuid4()}.webm"
    with factory() as db:
        db.add(
            Meeting(
                id=meeting_id,
                owner_id=uuid.uuid4(),
                title="Deleted",
                status="deleted",
                consent_confirmed_at=now,
                consent_policy_version="v1",
                created_at=now,
                updated_at=now,
                deleted_at=now,
            )
        )
        db.add(
            Recording(
                meeting_id=meeting_id,
                object_key=key,
                mime_type="audio/webm",
                size_bytes=4,
                sha256=hashlib.sha256(b"test").hexdigest(),
                upload_idempotency_key=uuid.uuid4(),
                uploaded_at=now,
                purge_after=now + timedelta(days=7),
            )
        )
        db.add(
            ProcessingJob(
                meeting_id=meeting_id,
                kind="process_recording",
                stage="summarizing",
                status="completed",
                cursor=1,
                attempts=1,
                max_attempts=3,
                run_after=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            TranscriptSegment(
                id=segment_id,
                meeting_id=meeting_id,
                sequence_no=0,
                start_ms=0,
                end_ms=1000,
                text="test",
                provider="fake",
                model="fake",
                created_at=now,
            )
        )
        db.add(
            Summary(
                meeting_id=meeting_id,
                schema_version="v1",
                prompt_version="v1",
                model="fake",
                content_json={
                    "overview": "Test",
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
    storage = FakeStorage()
    assert cleanup_once(factory, storage)["deleted"] == 1
    assert storage.deleted == [key]
    assert cleanup_once(factory, storage)["deleted"] == 0
    with factory() as db:
        assert db.get(Meeting, meeting_id) is None
        assert list(db.scalars(select(Recording))) == []
        assert list(db.scalars(select(ProcessingJob))) == []
        assert list(db.scalars(select(TranscriptSegment))) == []
        assert list(db.scalars(select(Summary))) == []
    engine.dispose()


def test_expired_raw_audio_is_purged_but_transcript_rows_remain():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    now = utc_now()
    meeting_id = uuid.uuid4()
    with factory() as db:
        db.add(
            Meeting(
                id=meeting_id,
                owner_id=uuid.uuid4(),
                title="Ready",
                status="ready",
                consent_confirmed_at=now,
                consent_policy_version="v1",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            Recording(
                meeting_id=meeting_id,
                object_key="private/expired.webm",
                mime_type="audio/webm",
                size_bytes=4,
                sha256=hashlib.sha256(b"test").hexdigest(),
                upload_idempotency_key=uuid.uuid4(),
                uploaded_at=now,
                purge_after=now - timedelta(seconds=1),
            )
        )
        db.commit()
    storage = FakeStorage()
    assert purge_expired_audio(factory, storage) == 1
    assert purge_expired_audio(factory, storage) == 0
    with factory() as db:
        assert db.get(Meeting, meeting_id) is not None
        recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        assert recording.deleted_at is not None
    engine.dispose()
