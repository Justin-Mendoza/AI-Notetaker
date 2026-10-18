import hashlib
import logging
import random
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.errors import ApiError
from app.models.job import ProcessingJob
from app.models.meeting import Meeting, utc_now
from app.models.recording import Recording
from app.models.summary import Summary
from app.models.transcript import TranscriptSegment
from app.services.media import inspect_audio
from app.services.storage import Storage, get_storage
from app.services.summarization import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    OpenAISummarizer,
    Summarizer,
    SummaryContent,
    SummaryError,
    SummarySegment,
    validate_summary,
)
from app.services.transcription import OpenAITranscriber, Transcriber, TranscriptionError
from app.settings import settings
from app.worker.audio import AudioChunk, AudioProcessingError, split_audio

LEASE_SECONDS = 300
SessionFactory = Callable[[], Session]
Splitter = Callable[[Path, int, Path], list[AudioChunk]]
logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class LeaseLost(Exception):
    pass


class ProcessingFailure(Exception):
    def __init__(self, code: str, transient: bool):
        self.code = code
        self.transient = transient
        super().__init__(code)


def claim_job(session_factory: SessionFactory, worker_id: str) -> uuid.UUID | None:
    now = utc_now()
    with session_factory() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(
                or_(
                    and_(ProcessingJob.status == "pending", ProcessingJob.run_after <= now),
                    and_(
                        ProcessingJob.status == "running",
                        ProcessingJob.lease_until < now,
                    ),
                )
            )
            .order_by(ProcessingJob.run_after, ProcessingJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        meeting = db.get(Meeting, job.meeting_id)
        if meeting is None or meeting.deleted_at is not None:
            job.status = "completed"
            job.locked_by = None
            job.lease_until = None
            db.commit()
            return None
        if job.status == "running" and job.attempts >= job.max_attempts:
            job.status = "failed"
            job.last_error_code = "WORKER_TIMEOUT"
            job.locked_by = None
            job.lease_until = None
            job.updated_at = now
            meeting.status = "failed"
            meeting.updated_at = now
            db.commit()
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_by = worker_id
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        job.updated_at = now
        if job.stage == "transcribing":
            meeting.status = "transcribing"
            meeting.updated_at = now
        elif job.stage == "summarizing":
            meeting.status = "summarizing"
            meeting.updated_at = now
        db.commit()
        return job.id


def requeue_incomplete_summaries(session_factory: SessionFactory) -> int:
    """Move jobs completed by the transcription-only worker to the summary stage."""
    count = 0
    with session_factory() as db:
        jobs = list(
            db.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.stage == "summarizing", ProcessingJob.status == "completed")
                .with_for_update(skip_locked=True)
            )
        )
        for job in jobs:
            meeting = db.get(Meeting, job.meeting_id)
            summary = db.scalar(select(Summary).where(Summary.meeting_id == job.meeting_id))
            if (
                meeting
                and meeting.deleted_at is None
                and meeting.status == "summarizing"
                and not summary
            ):
                job.status = "pending"
                job.run_after = utc_now()
                job.updated_at = utc_now()
                count += 1
        db.commit()
    return count


def renew_lease(session_factory: SessionFactory, job_id: uuid.UUID, worker_id: str) -> bool:
    now = utc_now()
    with session_factory() as db:
        result = db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.status == "running",
                ProcessingJob.locked_by == worker_id,
            )
            .values(lease_until=now + timedelta(seconds=LEASE_SECONDS), updated_at=now)
        )
        db.commit()
        return result.rowcount == 1


class LeaseHeartbeat:
    def __init__(self, session_factory: SessionFactory, job_id: uuid.UUID, worker_id: str):
        self.session_factory = session_factory
        self.job_id = job_id
        self.worker_id = worker_id
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self):
        def loop():
            while not self.stop.wait(LEASE_SECONDS / 3):
                try:
                    if not renew_lease(self.session_factory, self.job_id, self.worker_id):
                        return
                except Exception:
                    return

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)


def ensure_active(
    db: Session, job_id: uuid.UUID, worker_id: str, lock: bool = False
) -> tuple[ProcessingJob, Meeting]:
    statement = select(ProcessingJob).where(
        ProcessingJob.id == job_id,
        ProcessingJob.status == "running",
        ProcessingJob.locked_by == worker_id,
        ProcessingJob.lease_until > utc_now(),
    )
    if lock:
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        raise LeaseLost()
    meeting = db.get(Meeting, job.meeting_id)
    if meeting is None or meeting.deleted_at is not None:
        raise JobCancelled()
    return job, meeting


def save_segment(
    session_factory: SessionFactory,
    job_id: uuid.UUID,
    worker_id: str,
    chunk: AudioChunk,
    text: str,
    transcriber: Transcriber,
) -> None:
    with session_factory() as db:
        job, meeting = ensure_active(db, job_id, worker_id, lock=True)
        values = {
            "id": uuid.uuid4(),
            "meeting_id": meeting.id,
            "sequence_no": chunk.sequence_no,
            "start_ms": chunk.start_ms,
            "end_ms": chunk.end_ms,
            "text": text,
            "provider": transcriber.provider,
            "model": transcriber.model,
            "created_at": utc_now(),
        }
        if db.bind and db.bind.dialect.name == "postgresql":
            statement = (
                pg_insert(TranscriptSegment)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_transcript_sequence")
            )
        elif db.bind and db.bind.dialect.name == "sqlite":
            statement = (
                sqlite_insert(TranscriptSegment)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["meeting_id", "sequence_no"])
            )
        else:
            raise ProcessingFailure("UNSUPPORTED_DATABASE", transient=False)
        db.execute(statement)
        job.cursor = max(job.cursor, chunk.sequence_no + 1)
        job.updated_at = utc_now()
        db.commit()


def complete_transcription(
    session_factory: SessionFactory, job_id: uuid.UUID, worker_id: str, count: int
) -> None:
    with session_factory() as db:
        job, meeting = ensure_active(db, job_id, worker_id, lock=True)
        sequences = list(
            db.scalars(
                select(TranscriptSegment.sequence_no)
                .where(TranscriptSegment.meeting_id == meeting.id)
                .order_by(TranscriptSegment.sequence_no)
            )
        )
        if sequences != list(range(count)):
            raise ProcessingFailure("TRANSCRIPT_INCOMPLETE", transient=True)
        recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting.id))
        if recording is None:
            raise ProcessingFailure("MISSING_RECORDING", transient=False)
        now = utc_now()
        job.stage = "summarizing"
        job.status = "pending"
        job.attempts = 0
        job.cursor = count
        job.run_after = now
        job.lease_until = None
        job.locked_by = None
        job.updated_at = now
        meeting.status = "summarizing"
        meeting.updated_at = now
        recording.purge_after = now + timedelta(hours=settings.raw_audio_retention_hours)
        db.commit()


def save_summary(
    session_factory: SessionFactory,
    job_id: uuid.UUID,
    worker_id: str,
    content: SummaryContent,
    summarizer: Summarizer,
) -> None:
    with session_factory() as db:
        job, meeting = ensure_active(db, job_id, worker_id, lock=True)
        if job.stage != "summarizing":
            raise ProcessingFailure("INVALID_STAGE", transient=False)
        segment_ids = set(
            db.scalars(
                select(TranscriptSegment.id).where(TranscriptSegment.meeting_id == meeting.id)
            )
        )
        validated = validate_summary(content.model_dump(mode="json"), segment_ids)
        now = utc_now()
        stored = db.scalar(select(Summary).where(Summary.meeting_id == meeting.id))
        if stored is None:
            stored = Summary(
                meeting_id=meeting.id,
                schema_version=SCHEMA_VERSION,
                prompt_version=PROMPT_VERSION,
                model=summarizer.model,
                content_json=validated.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            db.add(stored)
        else:
            stored.schema_version = SCHEMA_VERSION
            stored.prompt_version = PROMPT_VERSION
            stored.model = summarizer.model
            stored.content_json = validated.model_dump(mode="json")
            stored.updated_at = now
        job.status = "completed"
        job.last_error_code = None
        job.lease_until = None
        job.locked_by = None
        job.updated_at = now
        meeting.status = "ready"
        meeting.updated_at = now
        db.commit()


def mark_failure(
    session_factory: SessionFactory,
    job_id: uuid.UUID,
    worker_id: str,
    failure: ProcessingFailure,
) -> None:
    with session_factory() as db:
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.locked_by != worker_id:
            return
        meeting = db.get(Meeting, job.meeting_id)
        if meeting is None or meeting.deleted_at is not None:
            return
        now = utc_now()
        job.last_error_code = failure.code
        job.locked_by = None
        job.lease_until = None
        job.updated_at = now
        if failure.transient and job.attempts < job.max_attempts:
            delay = min(300, 5 * 2 ** (job.attempts - 1)) + random.uniform(0, 1)
            job.status = "pending"
            job.run_after = now + timedelta(seconds=delay)
            meeting.status = "queued" if job.stage == "transcribing" else "summarizing"
        else:
            job.status = "failed"
            meeting.status = "failed"
        meeting.updated_at = now
        db.commit()


def process_job(
    session_factory: SessionFactory,
    job_id: uuid.UUID,
    worker_id: str,
    storage: Storage,
    transcriber: Transcriber,
    splitter: Splitter,
    summarizer: Summarizer | None = None,
) -> None:
    with session_factory() as db:
        job, meeting = ensure_active(db, job_id, worker_id)
        if job.stage == "summarizing":
            segments = list(
                db.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.meeting_id == meeting.id)
                    .order_by(TranscriptSegment.sequence_no)
                )
            )
            if not segments or [segment.sequence_no for segment in segments] != list(
                range(job.cursor)
            ):
                raise ProcessingFailure("TRANSCRIPT_INCOMPLETE", transient=True)
            summary_input = [
                SummarySegment(segment.id, segment.start_ms, segment.end_ms, segment.text)
                for segment in segments
            ]
        else:
            summary_input = None
        if summary_input is None and job.stage != "transcribing":
            raise ProcessingFailure("UNSUPPORTED_STAGE", transient=False)

    if summary_input is not None:

        def check_active() -> None:
            with session_factory() as db:
                ensure_active(db, job_id, worker_id)

        check_active()
        summarizer = summarizer or OpenAISummarizer()
        if isinstance(summarizer, OpenAISummarizer):
            summarizer.check_active = check_active
        try:
            result = summarizer.summarize(summary_input)
        except SummaryError as exc:
            raise ProcessingFailure(exc.code, exc.transient) from exc
        save_summary(session_factory, job_id, worker_id, result, summarizer)
        return

    with session_factory() as db:
        job, meeting = ensure_active(db, job_id, worker_id)
        if job.stage != "transcribing":
            raise ProcessingFailure("UNSUPPORTED_STAGE", transient=False)
        recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting.id))
        if recording is None or recording.deleted_at is not None:
            raise ProcessingFailure("MISSING_RECORDING", transient=False)
        key, mime, sha256 = recording.object_key, recording.mime_type, recording.sha256
        meeting_id = meeting.id

    with tempfile.TemporaryDirectory(prefix="meeting-worker-") as directory_text:
        directory = Path(directory_text)
        source = directory / "source.audio"
        with session_factory() as db:
            ensure_active(db, job_id, worker_id)
        try:
            storage.download(key, source)
        except Exception as exc:
            raise ProcessingFailure("STORAGE_READ_FAILED", transient=True) from exc
        digest = hashlib.sha256()
        with source.open("rb") as audio:
            while block := audio.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != sha256:
            raise ProcessingFailure("INVALID_AUDIO", transient=False)
        try:
            _, duration_ms = inspect_audio(source, mime)
        except ApiError as exc:
            raise ProcessingFailure(
                "LIMIT_EXCEEDED" if exc.status_code == 413 else "INVALID_AUDIO", transient=False
            ) from exc
        try:
            chunks = splitter(source, duration_ms, directory)
        except AudioProcessingError as exc:
            raise ProcessingFailure("INVALID_AUDIO", transient=False) from exc
        if not chunks:
            raise ProcessingFailure("INVALID_AUDIO", transient=False)
        with session_factory() as db:
            existing = set(
                db.scalars(
                    select(TranscriptSegment.sequence_no).where(
                        TranscriptSegment.meeting_id == meeting_id
                    )
                )
            )
        for chunk in chunks:
            with session_factory() as db:
                ensure_active(db, job_id, worker_id)
            if chunk.sequence_no in existing:
                continue
            try:
                text = transcriber.transcribe(chunk.path)
            except TranscriptionError as exc:
                raise ProcessingFailure(exc.code, exc.transient) from exc
            save_segment(session_factory, job_id, worker_id, chunk, text, transcriber)
        complete_transcription(session_factory, job_id, worker_id, len(chunks))


def run_once(
    worker_id: str,
    session_factory: SessionFactory = SessionLocal,
    storage: Storage | None = None,
    transcriber: Transcriber | None = None,
    splitter: Splitter = split_audio,
    heartbeat: bool = True,
    summarizer: Summarizer | None = None,
) -> bool:
    job_id = claim_job(session_factory, worker_id)
    if job_id is None:
        return False
    with session_factory() as db:
        claimed = db.get(ProcessingJob, job_id)
        if claimed is None:
            return False
        details = {
            "job_id": job_id,
            "meeting_id": claimed.meeting_id,
            "stage": claimed.stage,
            "attempt": claimed.attempts,
        }
    logger.info("job_claimed", extra=details)
    try:
        storage = storage or get_storage()
        transcriber = transcriber or OpenAITranscriber()
        if heartbeat:
            with LeaseHeartbeat(session_factory, job_id, worker_id):
                process_job(
                    session_factory, job_id, worker_id, storage, transcriber, splitter, summarizer
                )
        else:
            process_job(
                session_factory, job_id, worker_id, storage, transcriber, splitter, summarizer
            )
    except (JobCancelled, LeaseLost):
        logger.info("job_cancelled_or_lease_lost", extra=details)
    except ProcessingFailure as exc:
        mark_failure(session_factory, job_id, worker_id, exc)
        logger.warning("job_failed", extra={**details, "error_code": exc.code})
    except SummaryError as exc:
        mark_failure(session_factory, job_id, worker_id, ProcessingFailure(exc.code, exc.transient))
        logger.warning("job_failed", extra={**details, "error_code": exc.code})
    except TranscriptionError as exc:
        mark_failure(session_factory, job_id, worker_id, ProcessingFailure(exc.code, exc.transient))
        logger.warning("job_failed", extra={**details, "error_code": exc.code})
    except Exception:
        mark_failure(
            session_factory,
            job_id,
            worker_id,
            ProcessingFailure("PROCESSING_ERROR", transient=True),
        )
        logger.warning("job_failed", extra={**details, "error_code": "PROCESSING_ERROR"})
    else:
        logger.info("job_stage_completed", extra=details)
    return True
