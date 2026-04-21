"""ORM models for the RAG (Retrieval-Augmented Generation) pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Lesson


class LessonChunk(Base, UUIDMixin):
    """A single text chunk from a lesson, stored with its embedding vector.

    Each lesson is split into overlapping chunks at index time.  Chunks are
    write-once: re-indexing a lesson deletes all existing rows for that lesson
    and inserts a fresh set.

    Attributes:
        lesson_id: FK to the parent lesson; cascades on delete so chunks are
            automatically removed when a lesson is deleted.
        course_id: Denormalized FK to the course — stored here to avoid a
            multi-join when scoping RAG queries to a single course in Sprint 9.
        chunk_index: Zero-based position of this chunk within the lesson, used
            to reconstruct reading order for citations.
        source: Origin of the text — ``"content"`` for text-lesson body,
            ``"transcript"`` for video transcript plain text.
        body: The raw text of the chunk as sent to the embedding model.
        embedding: 1536-dimensional vector produced by
            ``text-embedding-3-small``.  ``None`` only transiently — the
            indexing task always populates this before committing.
        created_at: Row creation timestamp.
        lesson: Back-reference to the parent ``Lesson``.
    """

    __tablename__ = "lesson_chunks"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    lesson: Mapped[Lesson] = relationship("Lesson")
