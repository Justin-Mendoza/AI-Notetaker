"""Idempotent maintenance for private audio and deleted meetings."""

import logging
import re
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.job import ProcessingJob
from app.models.meeting import Meeting, utc_now
from app.models.recording import Recording
from app.models.summary import Summary
from app.models.transcript import TranscriptSegment
from app.observability import configure_logging
from app.services.storage import Storage, get_storage

SessionFactory = Callable[[], Session]
OBJECT_KEY_PATTERN = re.compile(
    r"^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.(webm|ogg|m4a|wav|mp3)$"
)


def expire_abandoned_meetings(session_factory: SessionFactory, days: int = 7) -> int:
    cutoff = utc_now() - timedelta(days=days)
    with session_factory() as db:
        meetings = list(
            db.scalars(
                select(Meeting).where(
                    Meeting.status.in_(["draft", "uploading"]),
                    Meeting.updated_at < cutoff,
                    Meeting.deleted_at.is_(None),
                )
            )
        )
        for meeting in meetings:
            meeting.deleted_at = utc_now()
            meeting.status = "deleted"
            meeting.updated_at = utc_now()
        db.commit()
        return len(meetings)


def cleanup_deleted_meetings(session_factory: SessionFactory, storage: Storage) -> int:
    with session_factory() as db:
        ids = list(db.scalars(select(Meeting.id).where(Meeting.deleted_at.is_not(None))))
    removed = 0
    for meeting_id in ids:
        with session_factory() as db:
            meeting = db.get(Meeting, meeting_id)
            if meeting is None or meeting.deleted_at is None:
                continue
            recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
            object_key = (
                recording.object_key if recording and recording.deleted_at is None else None
            )
        if object_key:
            try:
                storage.delete(object_key)
            except Exception:
                continue
        with session_factory() as db:
            meeting = db.get(Meeting, meeting_id)
            if meeting is None or meeting.deleted_at is None:
                continue
            db.execute(delete(Summary).where(Summary.meeting_id == meeting_id))
            db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
            db.execute(delete(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
            db.execute(delete(Recording).where(Recording.meeting_id == meeting_id))
            db.delete(meeting)
            db.commit()
            removed += 1
    return removed


def purge_expired_audio(session_factory: SessionFactory, storage: Storage) -> int:
    now = utc_now()
    with session_factory() as db:
        ids = list(
            db.scalars(
                select(Recording.id).where(
                    Recording.purge_after <= now, Recording.deleted_at.is_(None)
                )
            )
        )
    purged = 0
    for recording_id in ids:
        with session_factory() as db:
            recording = db.get(Recording, recording_id)
            if recording is None or recording.deleted_at is not None:
                continue
            key = recording.object_key
        try:
            storage.delete(key)
        except Exception:
            continue
        with session_factory() as db:
            recording = db.get(Recording, recording_id)
            if recording and recording.deleted_at is None:
                recording.deleted_at = utc_now()
                db.commit()
                purged += 1
    return purged


def sweep_orphaned_objects(
    session_factory: SessionFactory, storage: Storage, min_age_hours: int = 24
) -> int:
    with session_factory() as db:
        known_keys = set(db.scalars(select(Recording.object_key)))
    cutoff = utc_now() - timedelta(hours=min_age_hours)
    removed = 0
    for key, last_modified in storage.list_objects():
        if key in known_keys or not OBJECT_KEY_PATTERN.fullmatch(key) or last_modified >= cutoff:
            continue
        try:
            storage.delete(key)
            removed += 1
        except Exception:
            continue
    return removed


def cleanup_once(session_factory: SessionFactory, storage: Storage) -> dict[str, int]:
    abandoned = expire_abandoned_meetings(session_factory)
    deleted = cleanup_deleted_meetings(session_factory, storage)
    expired_audio = purge_expired_audio(session_factory, storage)
    orphans = sweep_orphaned_objects(session_factory, storage)
    return {
        "abandoned": abandoned,
        "deleted": deleted,
        "expired_audio": expired_audio,
        "orphans": orphans,
    }


def main() -> None:
    configure_logging()
    result = cleanup_once(SessionLocal, get_storage())
    logging.info("cleanup complete counts=%s", result)


if __name__ == "__main__":
    main()
