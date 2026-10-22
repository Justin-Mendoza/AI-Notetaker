import io
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter

from app.api.meetings import CurrentUser, DbSession, owned_meeting
from app.errors import ApiError
from app.models.slides import SlideDeck

router = APIRouter(prefix="/v1/meetings", tags=["slides"])
MAX_PDF_BYTES = 20 * 1024 * 1024


class SlidesOut(BaseModel):
    filename: str
    page_count: int
    references: dict[str, list[int]]


class SlideReference(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    pages: list[int] = Field(max_length=50)


def deck_for(db, meeting_id):
    deck = db.get(SlideDeck, meeting_id)
    if deck is None:
        raise ApiError(404, "SLIDES_NOT_FOUND", "No slides have been added")
    return deck


@router.get("/{meeting_id}/slides", response_model=SlidesOut | None)
def get_slides(meeting_id: uuid.UUID, owner_id: CurrentUser, db: DbSession):
    owned_meeting(db, meeting_id, owner_id)
    return db.get(SlideDeck, meeting_id)


@router.post("/{meeting_id}/slides", response_model=SlidesOut, status_code=201)
def upload_slides(
    meeting_id: uuid.UUID,
    owner_id: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
):
    owned_meeting(db, meeting_id, owner_id)
    if db.get(SlideDeck, meeting_id):
        raise ApiError(409, "SLIDES_EXIST", "Remove the current slides before adding another PDF")
    content = file.file.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise ApiError(413, "FILE_LIMIT", "Slides must be 20 MB or smaller")
    try:
        if not content.startswith(b"%PDF-"):
            raise ValueError()
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 500:
            raise ValueError()
        # Keep page visuals, but discard document scripts, attachments and annotations.
        writer = PdfWriter()
        for page in reader.pages:
            page.pop("/AA", None)
            page.pop("/Annots", None)
            writer.add_page(page)
        output = io.BytesIO()
        writer.write(output)
    except Exception as exc:
        raise ApiError(
            422, "INVALID_PDF", "Choose a valid, unencrypted PDF with 1–500 pages"
        ) from exc
    deck = SlideDeck(
        meeting_id=meeting_id,
        filename=Path(file.filename or "slides.pdf").name[:200],
        page_count=len(reader.pages),
        content=output.getvalue(),
        references={},
    )
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return deck


@router.get("/{meeting_id}/slides/pdf")
def get_pdf(meeting_id: uuid.UUID, owner_id: CurrentUser, db: DbSession):
    owned_meeting(db, meeting_id, owner_id)
    deck = deck_for(db, meeting_id)
    return Response(
        deck.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="slides.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/{meeting_id}/slides/references", response_model=SlidesOut)
def save_reference(
    meeting_id: uuid.UUID,
    body: SlideReference,
    owner_id: CurrentUser,
    db: DbSession,
):
    owned_meeting(db, meeting_id, owner_id)
    deck = deck_for(db, meeting_id)
    if any(page < 1 or page > deck.page_count for page in body.pages):
        raise ApiError(422, "INVALID_SLIDE", "Choose a page in this PDF")
    refs = dict(deck.references)
    if body.pages:
        refs[body.topic] = sorted(set(body.pages))
    else:
        refs.pop(body.topic, None)
    deck.references = refs
    db.commit()
    db.refresh(deck)
    return deck


@router.delete("/{meeting_id}/slides", status_code=204)
def delete_slides(meeting_id: uuid.UUID, owner_id: CurrentUser, db: DbSession):
    owned_meeting(db, meeting_id, owner_id)
    db.delete(deck_for(db, meeting_id))
    db.commit()
    return Response(status_code=204)
