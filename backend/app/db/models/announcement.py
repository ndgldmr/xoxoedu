"""ORM model for admin announcements sent to students."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course
    from app.db.models.user import User


class Announcement(Base, UUIDMixin):
    """An admin-authored message broadcast to enrolled students or the full platform.

    Attributes:
        title: Short subject line for the announcement (≤ 255 chars).
        body: Full announcement text (may contain Markdown).
        scope: ``"course"`` to target one course's students; ``"platform"`` for all students.
        course_id: Required when ``scope="course"``; ``None`` for platform-wide announcements.
        created_by: FK to the admin who created the announcement; ``None`` if admin deleted.
        created_at: Row creation timestamp (server-side).
        sent_at: Set when the email dispatch Celery task has been enqueued; ``None`` until sent.
        course: The targeted ``Course`` (eager-loadable).
        creator: The admin ``User`` who created the announcement.
    """

    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    course: Mapped[Optional[Course]] = relationship("Course", foreign_keys=[course_id])
    creator: Mapped[Optional[User]] = relationship("User", foreign_keys=[created_by])
