import hashlib
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.job import ProcessingJob
from app.models.meeting import Meeting, utc_now
from app.models.recording import Recording
from app.models.transcript import TranscriptSegment
from app.services.summarization import FakeSummarizer
from app.services.transcription import FakeTranscriber, TranscriptionError
from app.worker import audio, runner


@pytest.fixture
def worker_database():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    now = utc_now()
    meeting_id = uuid.uuid4()
    source = b"fake recorded audio"
    with factory() as db:
        db.add(
            Meeting(
                id=meeting_id,
                owner_id=uuid.uuid4(),
                title="Worker test",
                status="queued",
                consent_confirmed_at=now,
                consent_policy_version="v1",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            Recording(
                meeting_id=meeting_id,
                object_key="private/fake.webm",
                mime_type="audio/webm",
                size_bytes=len(source),
                sha256=hashlib.sha256(source).hexdigest(),
                upload_idempotency_key=uuid.uuid4(),
                uploaded_at=now,
                purge_after=now + timedelta(days=7),
            )
        )
        db.add(
            ProcessingJob(
                meeting_id=meeting_id,
                kind="process_recording",
                stage="transcribing",
                status="pending",
                cursor=0,
                attempts=0,
                max_attempts=3,
                run_after=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    yield factory, meeting_id, source
    engine.dispose()


class FakeStorage:
    def __init__(self, source):
        self.source = source

    def download(self, key, path):
        path.write_bytes(self.source)


def three_chunks(source: Path, duration_ms: int, directory: Path):
    chunks = []
    for sequence_no in range(3):
        path = directory / f"chunk_{sequence_no:04d}.mp3"
        path.write_bytes(b"chunk")
        chunks.append(
            audio.AudioChunk(sequence_no, sequence_no * 600000, (sequence_no + 1) * 600000, path)
        )
    return chunks


class FlakyTranscriber(FakeTranscriber):
    def __init__(self):
        super().__init__(["first", "second", "third"])
        self.failed = False

    def transcribe(self, path):
        number = int(path.stem.split("_")[-1])
        self.calls.append(number)
        if number == 1 and not self.failed:
            self.failed = True
            raise TranscriptionError("STT_TEMPORARY", transient=True)
        return self.texts[number]


def test_sixty_minute_audio_splits_in_order_under_limit(tmp_path, monkeypatch):
    source = tmp_path / "source.webm"
    source.write_bytes(b"source")

    def fake_run(args, **kwargs):
        Path(args[-1]).write_bytes(b"valid chunk")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    chunks = audio.split_audio(source, 60 * 60 * 1000, tmp_path)
    assert len(chunks) == 6
    assert [chunk.sequence_no for chunk in chunks] == list(range(6))
    assert [(chunk.start_ms, chunk.end_ms) for chunk in chunks] == [
        (index * 600000, (index + 1) * 600000) for index in range(6)
    ]
    assert all(0 < chunk.path.stat().st_size < audio.MAX_STT_BYTES for chunk in chunks)


def test_retry_keeps_completed_segments_without_duplicate_calls(worker_database, monkeypatch):
    factory, meeting_id, source = worker_database
    monkeypatch.setattr(runner, "inspect_audio", lambda path, mime: (mime, 1800000))
    transcriber = FlakyTranscriber()
    storage = FakeStorage(source)
    assert runner.run_once("worker-a", factory, storage, transcriber, three_chunks, heartbeat=False)
    with factory() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
        assert job.status == "pending"
        assert job.cursor == 1
        job.run_after = utc_now() - timedelta(seconds=1)
        db.commit()

    assert runner.run_once("worker-a", factory, storage, transcriber, three_chunks, heartbeat=False)
    with factory() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
        segments = list(
            db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence_no))
        )
        meeting = db.get(Meeting, meeting_id)
        assert job.status == "pending" and job.stage == "summarizing" and job.cursor == 3
        assert job.attempts == 0
        assert meeting.status == "summarizing"
        assert [segment.text for segment in segments] == ["first", "second", "third"]
        assert transcriber.calls == [0, 1, 1, 2]

    summary = FakeSummarizer(
        {
            "overview": "The group reviewed three points.",
            "key_points": ["Three points were discussed."],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
    )
    assert runner.run_once(
        "worker-a",
        factory,
        storage,
        transcriber,
        three_chunks,
        heartbeat=False,
        summarizer=summary,
    )
    with factory() as db:
        assert db.get(Meeting, meeting_id).status == "ready"
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
        assert job.status == "completed"
        assert transcriber.calls == [0, 1, 1, 2]
        assert summary.calls == 1


def test_expired_lease_can_be_reclaimed_and_old_worker_cannot_write(worker_database):
    factory, meeting_id, _ = worker_database
    job_id = runner.claim_job(factory, "old-worker")
    assert job_id is not None
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        job.lease_until = utc_now() - timedelta(seconds=1)
        db.commit()
    assert runner.claim_job(factory, "new-worker") == job_id
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.attempts == 2 and job.locked_by == "new-worker"
    with pytest.raises(runner.LeaseLost):
        runner.save_segment(
            factory,
            job_id,
            "old-worker",
            audio.AudioChunk(0, 0, 1000, Path("unused")),
            "text",
            FakeTranscriber(["text"]),
        )


def test_three_transient_failures_end_in_retryable_failed_state(worker_database, monkeypatch):
    factory, meeting_id, source = worker_database
    monkeypatch.setattr(runner, "inspect_audio", lambda path, mime: (mime, 1800000))

    class AlwaysFail(FakeTranscriber):
        def transcribe(self, path):
            raise TranscriptionError("STT_TEMPORARY", transient=True)

    for attempt in range(3):
        assert runner.run_once(
            "worker-a",
            factory,
            FakeStorage(source),
            AlwaysFail(["x"]),
            three_chunks,
            heartbeat=False,
        )
        with factory() as db:
            job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
            if attempt < 2:
                assert job.status == "pending"
                job.run_after = utc_now() - timedelta(seconds=1)
                db.commit()
            else:
                assert job.status == "failed" and job.attempts == 3
                assert db.get(Meeting, meeting_id).status == "failed"


def test_summary_retry_uses_saved_transcript_without_retranscription(worker_database, monkeypatch):
    factory, meeting_id, source = worker_database
    monkeypatch.setattr(runner, "inspect_audio", lambda path, mime: (mime, 1800000))
    transcriber = FakeTranscriber(["first", "second", "third"])
    storage = FakeStorage(source)
    assert runner.run_once("worker-a", factory, storage, transcriber, three_chunks, heartbeat=False)
    assert transcriber.calls == [0, 1, 2]

    bad_summary = FakeSummarizer({"overview": "Missing required fields"})
    assert runner.run_once(
        "worker-a",
        factory,
        storage,
        transcriber,
        three_chunks,
        heartbeat=False,
        summarizer=bad_summary,
    )
    with factory() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
        assert job.status == "pending" and job.stage == "summarizing"
        assert job.last_error_code == "SUMMARY_INVALID"
        assert db.get(Meeting, meeting_id).status == "summarizing"
        assert len(list(db.scalars(select(TranscriptSegment)))) == 3
        job.run_after = utc_now() - timedelta(seconds=1)
        db.commit()

    good_summary = FakeSummarizer(
        {
            "overview": "The group discussed three points.",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
    )
    assert runner.run_once(
        "worker-a",
        factory,
        storage,
        transcriber,
        three_chunks,
        heartbeat=False,
        summarizer=good_summary,
    )
    with factory() as db:
        assert db.get(Meeting, meeting_id).status == "ready"
        assert len(list(db.scalars(select(TranscriptSegment)))) == 3
        assert transcriber.calls == [0, 1, 2]
