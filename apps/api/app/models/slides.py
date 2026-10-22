import uuid

from sqlalchemy import JSON, ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SlideDeck(Base):
    __tablename__ = "slide_decks"

    meeting_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("meetings.id"), primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    page_count: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    references: Mapped[dict] = mapped_column(JSON, default=dict)
