"""ORM model for batch-linked live sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.batch import Batch


class LiveSession(Base, UUIDMixin, TimestampMixin):
    """A scheduled live session tied to a cohort batch.

    Live sessions represent synchronous learning events (e.g. Zoom calls,
    Google Meet, webinars) that are associated with a batch of enrolled
    students.  All datetimes are stored in UTC; the ``timezone`` column
    holds the IANA name used for display and iCal export.

    Status lifecycle: ``scheduled`` → ``canceled``.  Canceled sessions
    remain in the database for audit purposes but are excluded from student
    calendar feeds.

    Attributes:
        batch_id: FK to the parent batch; cascades on batch delete.
        title: Short label for the session (e.g. ``"Week 3 Q&A"``).
        description: Optional longer description shown to students.
        starts_at: UTC timestamp when the session begins.
        ends_at: UTC timestamp when the session ends.
        timezone: IANA timezone name for display and iCal ``TZID`` hints.
        provider: Optional platform label (e.g. ``"zoom"``, ``"google_meet"``).
        join_url: Protected URL distributed only to authenticated students.
        recording_url: Optional post-session recording link.
        status: ``"scheduled"`` (default) or ``"canceled"``.
        reminder_task_id: Celery task ID of the pending reminder task.
            Written on session create/reschedule; used for best-effort revoke
            when the session is edited or canceled.
        batch: The parent ``Batch``.
    """

    __tablename__ = "live_sessions"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    join_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="scheduled"
    )
    reminder_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    batch: Mapped[Batch] = relationship("Batch", foreign_keys=[batch_id])
