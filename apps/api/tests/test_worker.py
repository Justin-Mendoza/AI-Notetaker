import hashlib
import shutil
import subprocess
import uuid
from datetime import UTC, timedelta
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
from app.models.summary import Summary
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


def test_sixty_minute_job_reaches_ready_with_all_six_chunks(worker_database, monkeypatch):
    factory, meeting_id, source = worker_database
    monkeypatch.setattr(runner, "inspect_audio", lambda path, mime: (mime, 3_600_000))

    def six_chunks(path: Path, duration_ms: int, directory: Path):
        assert duration_ms == 3_600_000
        result = []
        for number in range(6):
            chunk_path = directory / f"chunk_{number:04d}.mp3"
            chunk_path.write_bytes(b"audio")
            result.append(
                audio.AudioChunk(number, number * 600_000, (number + 1) * 600_000, chunk_path)
            )
        return result

    transcriber = FakeTranscriber([f"Part {number}" for number in range(6)])
    summarizer = FakeSummarizer(
        {
            "overview": "Six parts were reviewed.",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
    )
    storage = FakeStorage(source)
    assert runner.run_once("worker", factory, storage, transcriber, six_chunks, heartbeat=False)
    assert runner.run_once(
        "worker",
        factory,
        storage,
        transcriber,
        six_chunks,
        heartbeat=False,
        summarizer=summarizer,
    )
    with factory() as db:
        assert db.get(Meeting, meeting_id).status == "ready"
        segments = list(
            db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence_no))
        )
        assert [(segment.sequence_no, segment.text) for segment in segments] == [
            (number, f"Part {number}") for number in range(6)
        ]
    assert transcriber.calls == list(range(6))
    assert summarizer.calls == 1


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg is not installed"
)
def test_real_two_hour_fixture_processes_all_twelve_chunks(worker_database, tmp_path):
    factory, meeting_id, _ = worker_database
    fixture = tmp_path / "two-hours.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t",
            "7200",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(fixture),
        ],
        check=True,
        timeout=300,
    )
    source = fixture.read_bytes()
    assert len(source) > 25_000_000
    with factory() as db:
        recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        recording.mime_type = "audio/mpeg"
        recording.size_bytes = len(source)
        recording.sha256 = hashlib.sha256(source).hexdigest()
        db.commit()
    transcriber = FakeTranscriber([f"Part {number}" for number in range(12)])
    summarizer = FakeSummarizer(
        {
            "overview": "Twelve parts were reviewed.",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
    )
    storage = FakeStorage(source)
    assert runner.run_once("worker", factory, storage, transcriber, heartbeat=False)
    assert runner.run_once(
        "worker", factory, storage, transcriber, heartbeat=False, summarizer=summarizer
    )
    with factory() as db:
        assert db.get(Meeting, meeting_id).status == "ready"
        segments = list(
            db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence_no))
        )
        assert len(segments) == 12
        assert [segment.text for segment in segments] == [f"Part {number}" for number in range(12)]
    assert transcriber.calls == list(range(12))


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


def test_repeated_worker_crashes_stop_at_attempt_limit(worker_database):
    factory, meeting_id, _ = worker_database
    job_id = runner.claim_job(factory, "worker-a")
    assert job_id is not None
    for attempt in (2, 3):
        with factory() as db:
            job = db.get(ProcessingJob, job_id)
            job.lease_until = utc_now() - timedelta(seconds=1)
            db.commit()
        assert runner.claim_job(factory, "worker-b") == job_id
        with factory() as db:
            assert db.get(ProcessingJob, job_id).attempts == attempt
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        job.lease_until = utc_now() - timedelta(seconds=1)
        db.commit()
    assert runner.claim_job(factory, "worker-c") is None
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.status == "failed" and job.last_error_code == "WORKER_TIMEOUT"
        assert db.get(Meeting, meeting_id).status == "failed"


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
                run_after = (
                    job.run_after.replace(tzinfo=UTC)
                    if job.run_after.tzinfo is None
                    else job.run_after
                )
                assert (run_after - utc_now()).total_seconds() >= (4 if attempt == 0 else 9)
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
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
        assert job.last_error_code is None
        assert transcriber.calls == [0, 1, 2]


def test_regenerated_class_notes_replace_summary_without_retranscription(
    worker_database, monkeypatch
):
    factory, meeting_id, source = worker_database
    monkeypatch.setattr(runner, "inspect_audio", lambda path, mime: (mime, 1800000))
    transcriber = FakeTranscriber(["First concept", "Second concept", "Third concept"])
    storage = FakeStorage(source)
    assert runner.run_once("worker", factory, storage, transcriber, three_chunks, heartbeat=False)
    initial = FakeSummarizer(
        {
            "overview": "Three concepts were taught.",
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
    )
    assert runner.run_once(
        "worker",
        factory,
        storage,
        transcriber,
        three_chunks,
        heartbeat=False,
        summarizer=initial,
    )
    with factory() as db:
        first_segment = db.scalar(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.sequence_no)
        )
        first_segment_id = first_segment.id
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
        job.status = "pending"
        job.attempts = 0
        job.run_after = utc_now()
        db.get(Meeting, meeting_id).status = "summarizing"
        db.commit()
    updated = FakeSummarizer(
        {
            "overview": "Three concepts were taught in order.",
            "key_points": ["Review the first concept."],
            "topics": [
                {
                    "heading": "First concept",
                    "summary": "The instructor introduced the first concept.",
                    "key_details": ["It came before the second concept."],
                    "evidence_segment_ids": [str(first_segment_id)],
                }
            ],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
    )
    assert runner.run_once(
        "worker",
        factory,
        storage,
        transcriber,
        three_chunks,
        heartbeat=False,
        summarizer=updated,
    )
    with factory() as db:
        summaries = list(db.scalars(select(Summary).where(Summary.meeting_id == meeting_id)))
        assert len(summaries) == 1
        assert summaries[0].content_json["topics"][0]["heading"] == "First concept"
        assert db.get(Meeting, meeting_id).status == "ready"
    assert transcriber.calls == [0, 1, 2]


def test_deletion_during_provider_call_prevents_transcript_write(worker_database, monkeypatch):
    factory, meeting_id, source = worker_database
    monkeypatch.setattr(runner, "inspect_audio", lambda path, mime: (mime, 1800000))

    class DeleteDuringCall(FakeTranscriber):
        def transcribe(self, path):
            with factory() as db:
                meeting = db.get(Meeting, meeting_id)
                meeting.deleted_at = utc_now()
                meeting.status = "deleted"
                db.commit()
            return "must not be saved"

    assert runner.run_once(
        "worker-a",
        factory,
        FakeStorage(source),
        DeleteDuringCall(["x"]),
        three_chunks,
        heartbeat=False,
    )
    with factory() as db:
        assert list(db.scalars(select(TranscriptSegment))) == []


def test_live_capture_fills_only_missing_minutes(worker_database, monkeypatch):
    factory, meeting_id, source = worker_database
    with factory() as db:
        job = db.scalar(select(ProcessingJob))
        job.kind = "process_live_recording"
        db.add(
            TranscriptSegment(
                meeting_id=meeting_id,
                sequence_no=0,
                start_ms=0,
                end_ms=60000,
                text="Saved during class",
                provider="cohere-local",
                model="cohere-test",
                created_at=utc_now(),
            )
        )
        db.commit()
    monkeypatch.setattr(runner, "inspect_audio", lambda *args: ("audio/webm", 125000))

    def live_split(path, duration, directory, chunk_ms):
        assert chunk_ms == 60000
        chunks = []
        for i in range(3):
            chunk = directory / f"chunk_{i:04d}.mp3"
            chunk.write_bytes(b"audio")
            chunks.append(audio.AudioChunk(i, i * 60000, min((i + 1) * 60000, duration), chunk))
        return chunks

    monkeypatch.setattr(runner, "split_audio", live_split)
    transcriber = FakeTranscriber(["Do not call again", "Second minute", "Last five seconds"])
    assert runner.run_once("worker", factory, FakeStorage(source), transcriber, heartbeat=False)
    assert transcriber.calls == [1, 2]
    with factory() as db:
        segments = list(
            db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence_no))
        )
        assert [segment.text for segment in segments] == [
            "Saved during class",
            "Second minute",
            "Last five seconds",
        ]
        assert db.scalar(select(ProcessingJob)).stage == "summarizing"


@pytest.mark.parametrize(
    "saved_sequences, expected_stage", [([0, 1], "summarizing"), ([0, 2], "transcribing")]
)
def test_shorter_recovered_backup_retains_live_minutes_without_accepting_gaps(
    worker_database, monkeypatch, saved_sequences, expected_stage
):
    factory, meeting_id, source = worker_database
    with factory() as db:
        db.scalar(select(ProcessingJob)).kind = "process_live_recording"
        for sequence in saved_sequences:
            db.add(
                TranscriptSegment(
                    meeting_id=meeting_id,
                    sequence_no=sequence,
                    start_ms=sequence * 60000,
                    end_ms=(sequence + 1) * 60000,
                    text=f"Confirmed minute {sequence + 1}",
                    provider="cohere-local",
                    model="test",
                    created_at=utc_now(),
                )
            )
        db.commit()
    monkeypatch.setattr(runner, "inspect_audio", lambda *args: ("audio/webm", 50000))

    def recovered_split(path, duration, directory, chunk_ms):
        chunk = directory / "chunk_0000.mp3"
        chunk.write_bytes(b"recovered")
        return [audio.AudioChunk(0, 0, duration, chunk)]

    monkeypatch.setattr(runner, "split_audio", recovered_split)
    transcriber = FakeTranscriber([])
    runner.run_once("worker", factory, FakeStorage(source), transcriber, heartbeat=False)
    assert transcriber.calls == []
    with factory() as db:
        job = db.scalar(select(ProcessingJob))
        assert job.stage == expected_stage
        if expected_stage == "summarizing":
            assert job.cursor == 2
            assert job.last_error_code is None
        else:
            assert job.last_error_code == "TRANSCRIPT_INCOMPLETE"
        assert (
            list(
                db.scalars(
                    select(TranscriptSegment.sequence_no).order_by(TranscriptSegment.sequence_no)
                )
            )
            == saved_sequences
        )
