import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.db.session import get_db
from app.errors import ApiError
from app.models.meeting import Meeting, utc_now

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])
CurrentUser = Annotated[uuid.UUID, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


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


class MeetingDetailResponse(MeetingResponse):
    recording: None
    job: None
    has_transcript: bool
    has_summary: bool


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
    value = json.dumps([meeting.created_at.isoformat(), str(meeting.id)]).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        date_text, id_text = json.loads(raw)
        return datetime.fromisoformat(date_text), uuid.UUID(id_text)
    except (ValueError, TypeError, IndexError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiError(422, "INVALID_CURSOR", "The page cursor is invalid") from exc


@router.post("", status_code=201, response_model=MeetingResponse)
def create_meeting(
    body: CreateMeeting,
    owner_id: CurrentUser,
    db: DbSession,
) -> dict:
    now = utc_now()
    meeting = Meeting(
        owner_id=owner_id,
        title=body.title or "Untitled meeting",
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
    return {
        "meeting": MeetingOut.model_validate(meeting),
        "recording": None,
        "job": None,
        "has_transcript": False,
        "has_summary": False,
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
