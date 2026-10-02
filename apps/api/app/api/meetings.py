import base64
import binascii
import hashlib
import json
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.local import get_current_user
from app.db.session import get_db
from app.errors import ApiError
from app.models.job import ProcessingJob
from app.models.meeting import Meeting, utc_now
from app.models.recording import Recording
from app.models.summary import Summary
from app.models.transcript import TranscriptSegment
from app.services.media import MAX_DURATION_MS, MAX_FILE_BYTES, inspect_audio
from app.services.storage import Storage, get_storage
from app.services.summarization import SummaryContent
from app.settings import settings

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
PrivateStorage = Annotated[Storage, Depends(get_storage)]


class CreateMeeting(BaseModel):
    title: str | None = None
    consent_confirmed: Literal[True]
    consent_policy_version: str = Field(min_length=1, max_length=32)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed or len(trimmed) > 160:
            raise ValueError("title must contain 1–160 characters")
        return trimmed


class RenameMeeting(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed or len(trimmed) > 160:
            raise ValueError("title must contain 1–160 characters")
        return trimmed


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    consent_confirmed_at: datetime
    consent_policy_version: str
    created_at: datetime
    updated_at: datetime


class MeetingResponse(BaseModel):
    meeting: MeetingOut


class MeetingListResponse(BaseModel):
    items: list[MeetingOut]
    next_cursor: str | None


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    stage: str
    attempts: int
    cursor: int
    last_error_code: str | None


class MeetingDetailResponse(MeetingResponse):
    recording: RecordingOut | None
    job: JobOut | None
    has_transcript: bool
    has_summary: bool


class UploadResponse(BaseModel):
    meeting_id: uuid.UUID
    status: Literal["queued"]


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_no: int
    start_ms: int
    end_ms: int
    text: str


class TranscriptResponse(BaseModel):
    segments: list[SegmentOut]
    full_text: str


class RetryResponse(BaseModel):
    status: str


class SummaryResponse(BaseModel):
    summary: SummaryContent


def owned_meeting(db: Session, meeting_id: uuid.UUID, owner_id: uuid.UUID) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.owner_id == owner_id,
            Meeting.deleted_at.is_(None),
        )
    )
    if meeting is None:
        raise ApiError(404, "MEETING_NOT_FOUND", "Meeting not found")
    return meeting


def encode_cursor(meeting: Meeting) -> str:
    created_at = meeting.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    value = json.dumps([created_at.isoformat(), str(meeting.id)]).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        date_text, id_text = json.loads(raw)
        created_at = datetime.fromisoformat(date_text)
        if created_at.tzinfo is None:
            raise ValueError("cursor date needs a timezone")
        return created_at, uuid.UUID(id_text)
    except (ValueError, TypeError, IndexError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiError(422, "INVALID_CURSOR", "The page cursor is invalid") from exc


@router.post("", status_code=201, response_model=MeetingResponse)
def create_meeting(
    body: CreateMeeting,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    now = utc_now()
    recent = db.scalar(
        select(func.count(Meeting.id)).where(
            Meeting.owner_id == owner_id, Meeting.created_at >= now - timedelta(hours=1)
        )
    )
    if recent >= settings.max_meetings_per_hour:
        raise ApiError(429, "RATE_LIMITED", "Too many meetings were created recently")
    meeting = Meeting(
        owner_id=owner_id,
        title=body.title or "Untitled class",
        status="draft",
        consent_confirmed_at=now,
        consent_policy_version=body.consent_policy_version,
        created_at=now,
        updated_at=now,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return {"meeting": MeetingOut.model_validate(meeting)}


@router.get("", response_model=MeetingListResponse)
def list_meetings(
    owner_id: CurrentUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=512),
) -> dict:
    statement = select(Meeting).where(Meeting.owner_id == owner_id, Meeting.deleted_at.is_(None))
    if cursor:
        created_at, meeting_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                Meeting.created_at < created_at,
                and_(Meeting.created_at == created_at, Meeting.id < meeting_id),
            )
        )
    statement = statement.order_by(Meeting.created_at.desc(), Meeting.id.desc()).limit(limit + 1)
    rows = list(db.scalars(statement))
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [MeetingOut.model_validate(row) for row in page],
        "next_cursor": encode_cursor(page[-1]) if has_more else None,
    }


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
def get_meeting(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    meeting = owned_meeting(db, meeting_id, owner_id)
    recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
    summary = db.scalar(select(Summary).where(Summary.meeting_id == meeting_id))
    return {
        "meeting": MeetingOut.model_validate(meeting),
        "recording": RecordingOut.model_validate(recording) if recording else None,
        "job": JobOut.model_validate(job) if job else None,
        "has_transcript": bool(job and job.stage == "summarizing"),
        "has_summary": bool(summary and meeting.status in {"ready", "summarizing", "failed"}),
    }


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def rename_meeting(
    meeting_id: uuid.UUID,
    body: RenameMeeting,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    meeting = owned_meeting(db, meeting_id, owner_id)
    meeting.title = body.title
    meeting.updated_at = utc_now()
    db.commit()
    db.refresh(meeting)
    return {"meeting": MeetingOut.model_validate(meeting)}


@router.post("/{meeting_id}/recording", status_code=202, response_model=UploadResponse)
def upload_recording(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
    storage: PrivateStorage,
    file: Annotated[UploadFile, File()],
    duration_ms: Annotated[int, Form(gt=0, le=MAX_DURATION_MS)],
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> dict:
    meeting = owned_meeting(db, meeting_id, owner_id)
    prior = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    if prior:
        if prior.upload_idempotency_key == idempotency_key:
            return {"meeting_id": meeting_id, "status": "queued"}
        raise ApiError(409, "RECORDING_EXISTS", "This meeting already has a recording")
    recent_uploads = db.scalar(
        select(func.count(Recording.id))
        .join(Meeting, Recording.meeting_id == Meeting.id)
        .where(
            Meeting.owner_id == owner_id,
            Recording.uploaded_at >= utc_now() - timedelta(hours=1),
        )
    )
    if recent_uploads >= settings.max_uploads_per_hour:
        raise ApiError(429, "RATE_LIMITED", "Too many recordings were uploaded recently")
    if meeting.status not in {"draft", "uploading"} or (
        meeting.status == "uploading" and meeting.upload_key != idempotency_key
    ):
        raise ApiError(409, "INVALID_STATE", "This meeting is not accepting a recording")

    meeting.status = "uploading"
    meeting.upload_key = idempotency_key
    meeting.updated_at = utc_now()
    db.commit()

    temporary_path: Path | None = None
    object_key: str | None = None
    object_saved = False
    try:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(prefix="meeting-upload-", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ApiError(413, "FILE_LIMIT", "Recordings must be 100 MB or smaller")
                digest.update(chunk)
                temporary.write(chunk)
        if size == 0:
            raise ApiError(415, "INVALID_MEDIA", "The recording is empty")
        mime_type, actual_duration_ms = inspect_audio(temporary_path, file.content_type or "")
        extension = {
            "audio/webm": "webm",
            "video/webm": "webm",
            "audio/ogg": "ogg",
            "audio/mp4": "m4a",
            "audio/x-m4a": "m4a",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/mpeg": "mp3",
        }[mime_type]
        object_key = f"{owner_id}/{meeting_id}/{uuid.uuid4()}.{extension}"
        storage.upload(temporary_path, object_key, mime_type)
        object_saved = True

        locked = db.scalar(select(Meeting).where(Meeting.id == meeting_id).with_for_update())
        if locked is None or locked.deleted_at is not None or locked.owner_id != owner_id:
            raise ApiError(404, "MEETING_NOT_FOUND", "Meeting not found")
        existing = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        if existing:
            if existing.upload_idempotency_key == idempotency_key:
                return {"meeting_id": meeting_id, "status": "queued"}
            raise ApiError(409, "RECORDING_EXISTS", "This meeting already has a recording")
        if locked.status != "uploading" or locked.upload_key != idempotency_key:
            raise ApiError(409, "INVALID_STATE", "This meeting is not accepting a recording")
        now = utc_now()
        db.add(
            Recording(
                meeting_id=meeting_id,
                object_key=object_key,
                mime_type=mime_type,
                size_bytes=size,
                sha256=digest.hexdigest(),
                upload_idempotency_key=idempotency_key,
                uploaded_at=now,
                purge_after=now + timedelta(days=settings.failed_audio_retention_days),
            )
        )
        db.add(
            ProcessingJob(
                meeting_id=meeting_id,
                kind="process_recording",
                status="pending",
                attempts=0,
                max_attempts=3,
                run_after=now,
                created_at=now,
                updated_at=now,
            )
        )
        locked.status = "queued"
        locked.duration_ms = actual_duration_ms
        locked.ended_at = now
        locked.started_at = now - timedelta(milliseconds=actual_duration_ms)
        locked.updated_at = now
        db.commit()
        object_saved = False
        return {"meeting_id": meeting_id, "status": "queued"}
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        if existing and existing.upload_idempotency_key == idempotency_key:
            return {"meeting_id": meeting_id, "status": "queued"}
        raise ApiError(409, "RECORDING_EXISTS", "This meeting already has a recording") from exc
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        if object_saved and object_key:
            try:
                storage.delete(object_key)
            except Exception:
                pass  # The maintenance orphan sweep removes a failed cleanup.
        if meeting_id:
            db.rollback()
            failed = db.scalar(select(Meeting).where(Meeting.id == meeting_id))
            recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
            if (
                failed
                and recording is None
                and failed.status == "uploading"
                and failed.upload_key == idempotency_key
            ):
                failed.status = "draft"
                failed.upload_key = None
                failed.updated_at = utc_now()
                db.commit()


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
def get_transcript(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    owned_meeting(db, meeting_id, owner_id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id))
    if job is None or job.stage != "summarizing":
        raise ApiError(404, "TRANSCRIPT_NOT_READY", "Transcript is not ready")
    segments = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.sequence_no)
        )
    )
    return {
        "segments": [SegmentOut.model_validate(segment) for segment in segments],
        "full_text": "\n".join(segment.text for segment in segments if segment.text),
    }


@router.get("/{meeting_id}/summary", response_model=SummaryResponse)
def get_summary(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    meeting = owned_meeting(db, meeting_id, owner_id)
    summary = db.scalar(select(Summary).where(Summary.meeting_id == meeting_id))
    if summary is None or meeting.status not in {"ready", "summarizing", "failed"}:
        raise ApiError(404, "SUMMARY_NOT_READY", "Summary is not ready")
    return {"summary": SummaryContent.model_validate(summary.content_json)}


@router.post("/{meeting_id}/regenerate", status_code=202, response_model=RetryResponse)
def regenerate_summary(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    meeting = db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id, Meeting.owner_id == owner_id, Meeting.deleted_at.is_(None))
        .with_for_update()
    )
    if meeting is None:
        raise ApiError(404, "MEETING_NOT_FOUND", "Meeting not found")
    if meeting.status != "ready":
        raise ApiError(409, "INVALID_STATE", "Notes can be regenerated after processing completes")
    job = db.scalar(
        select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id).with_for_update()
    )
    summary = db.scalar(select(Summary).where(Summary.meeting_id == meeting_id))
    segment_count = db.scalar(
        select(func.count(TranscriptSegment.id)).where(TranscriptSegment.meeting_id == meeting_id)
    )
    if (
        job is None
        or job.stage != "summarizing"
        or job.status != "completed"
        or summary is None
        or not job.cursor
        or segment_count != job.cursor
    ):
        raise ApiError(409, "TRANSCRIPT_INCOMPLETE", "The saved transcript is incomplete")
    now = utc_now()
    window_at = job.manual_retry_window_at
    if window_at and window_at.tzinfo is None:
        window_at = window_at.replace(tzinfo=UTC)
    if window_at is None or window_at < now - timedelta(hours=1):
        job.manual_retry_window_at = now
        job.manual_retry_count = 0
    if job.manual_retry_count >= settings.max_manual_retries_per_hour:
        raise ApiError(429, "RATE_LIMITED", "Wait before regenerating notes again")
    job.manual_retry_count += 1
    job.status = "pending"
    job.attempts = 0
    job.run_after = now
    job.lease_until = None
    job.locked_by = None
    job.last_error_code = None
    job.updated_at = now
    meeting.status = "summarizing"
    meeting.updated_at = now
    db.commit()
    return {"status": "summarizing"}


@router.post("/{meeting_id}/retry", status_code=202, response_model=RetryResponse)
def retry_meeting(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    meeting = owned_meeting(db, meeting_id, owner_id)
    job = db.scalar(
        select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id).with_for_update()
    )
    if job is None or job.status != "failed" or meeting.status != "failed":
        raise ApiError(409, "INVALID_STATE", "This meeting cannot be retried")
    if job.last_error_code in {"INVALID_AUDIO", "LIMIT_EXCEEDED", "MISSING_RECORDING"}:
        raise ApiError(409, "PERMANENT_FAILURE", "This recording cannot be retried")
    recording = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
    if job.stage == "transcribing" and (recording is None or recording.deleted_at is not None):
        raise ApiError(409, "RECORDING_EXPIRED", "The recording is no longer available")
    now = utc_now()
    window_at = job.manual_retry_window_at
    if window_at and window_at.tzinfo is None:
        window_at = window_at.replace(tzinfo=UTC)
    if window_at is None or window_at < now - timedelta(hours=1):
        job.manual_retry_window_at = now
        job.manual_retry_count = 0
    if job.manual_retry_count >= settings.max_manual_retries_per_hour:
        raise ApiError(429, "RATE_LIMITED", "Wait before retrying this meeting again")
    job.manual_retry_count += 1
    job.status = "pending"
    job.attempts = 0
    job.run_after = now
    job.lease_until = None
    job.locked_by = None
    job.last_error_code = None
    job.updated_at = now
    meeting.status = "queued" if job.stage == "transcribing" else "summarizing"
    meeting.updated_at = now
    db.commit()
    return {"status": meeting.status}


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
) -> Response:
    meeting = db.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id, Meeting.owner_id == owner_id, Meeting.deleted_at.is_(None))
        .with_for_update()
    )
    if meeting is None:
        raise ApiError(404, "MEETING_NOT_FOUND", "Meeting not found")
    now = utc_now()
    meeting.deleted_at = now
    meeting.status = "deleted"
    meeting.updated_at = now
    job = db.scalar(
        select(ProcessingJob).where(ProcessingJob.meeting_id == meeting_id).with_for_update()
    )
    if job:
        job.status = "completed"
        job.lease_until = None
        job.locked_by = None
        job.updated_at = now
    db.commit()
    return Response(status_code=204)
