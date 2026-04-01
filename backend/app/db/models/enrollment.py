"""ORM models for enrollment, lesson progress, notes, and bookmarks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course, Lesson
    from app.db.models.user import User


class Enrollment(Base, UUIDMixin):
    """Records a student's membership in a course.

    The ``status`` column tracks the lifecycle: ``active`` on enroll,
    ``unenrolled`` on soft-delete, and ``completed`` when all lessons are
    finished.  The unique constraint on ``(user_id, course_id)`` prevents
    duplicate rows; re-enroll restores the existing record.

    Attributes:
        user_id: FK to the enrolling student; cascades on user delete.
        course_id: FK to the enrolled course; cascades on course delete.
        status: Current state (``"active"``, ``"unenrolled"``, ``"completed"``).
        enrolled_at: Timestamp set by the database when the row is first inserted.
        completed_at: Set when the student completes all course lessons.
        payment_id: Optional Stripe payment reference; populated in Sprint 5.
        user: The enrolled ``User``.
        course: The ``Course`` being enrolled in.
    """

    __tablename__ = "enrollments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])


class LessonProgress(Base, UUIDMixin, TimestampMixin):
    """Tracks a student's progress on an individual lesson.

    Status advances forward only: ``not_started`` → ``in_progress`` →
    ``completed``.  ``watch_seconds`` is updated on every save to support
    resume-from-position.  The unique constraint on ``(user_id, lesson_id)``
    makes every write an upsert.

    Attributes:
        user_id: FK to the student; cascades on user delete.
        lesson_id: FK to the lesson being tracked; cascades on lesson delete.
        status: Current state (``"not_started"``, ``"in_progress"``, ``"completed"``).
        watch_seconds: Cumulative seconds of video watched; used for resume.
        completed_at: Set when ``status`` first transitions to ``"completed"``.
        user: The owning ``User``.
        lesson: The ``Lesson`` being tracked.
    """

    __tablename__ = "lesson_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    watch_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])


class UserNote(Base, UUIDMixin, TimestampMixin):
    """A private, freeform text note written by a student on a specific lesson.

    One note per ``(user_id, lesson_id)`` pair is enforced by a unique constraint.
    Writes are upserts: creating a note when one already exists updates ``content``.

    Attributes:
        user_id: FK to the note author; cascades on user delete.
        lesson_id: FK to the lesson the note is attached to; cascades on lesson delete.
        content: Raw note text; may contain Markdown.
        user: The owning ``User``.
        lesson: The ``Lesson`` this note is attached to.
    """

    __tablename__ = "user_notes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])


class UserBookmark(Base, UUIDMixin):
    """A student's bookmark on a lesson for quick navigation.

    One bookmark per ``(user_id, lesson_id)`` pair; toggling removes the row
    if it exists, or creates it if absent.

    Attributes:
        user_id: FK to the student who bookmarked the lesson; cascades on user delete.
        lesson_id: FK to the bookmarked lesson; cascades on lesson delete.
        created_at: Timestamp set by the database on INSERT.
        user: The owning ``User``.
        lesson: The ``Lesson`` bookmarked.
    """

    __tablename__ = "user_bookmarks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])
