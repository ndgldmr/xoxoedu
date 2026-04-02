"""ORM models for assignments and assignment file submissions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Lesson
    from app.db.models.user import User


class Assignment(Base, UUIDMixin, TimestampMixin):
    """An instructor-defined file-submission assignment attached to a lesson.

    Students respond by uploading a file to Cloudflare R2 via a presigned PUT
    URL.  Allowed file types and maximum size are enforced by the service layer
    before the upload URL is issued.

    Attributes:
        lesson_id: FK to the lesson this assignment belongs to; cascades on delete.
        title: Short display name for the assignment.
        instructions: Full assignment brief shown to students (may contain Markdown).
        max_file_size_bytes: Upload size limit in bytes (default 10 MiB).
        allowed_extensions: Permitted file extensions, e.g. ``["pdf", "docx"]``.
        lesson: The parent ``Lesson``.
    """

    __tablename__ = "assignments"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    max_file_size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10_485_760
    )
    allowed_extensions: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])


class AssignmentSubmission(Base, UUIDMixin, TimestampMixin):
    """Records a student's file upload for an assignment.

    The upload flow is two-phase: the service creates this row with
    ``submitted_at=None`` and returns a presigned PUT URL; once the upload
    completes the student calls ``POST /confirm`` to stamp ``submitted_at``.

    ``scan_status`` defaults to ``"pending"`` as a placeholder.  Actual
    virus scanning is wired in Sprint 12.

    Attributes:
        user_id: FK to the submitting student; cascades on user delete.
        assignment_id: FK to the assignment; cascades on assignment delete.
        file_key: R2 object key (path within the bucket).
        file_name: Original filename provided by the student.
        file_size: File size in bytes declared by the student at upload-request time.
        mime_type: MIME type declared by the student at upload-request time.
        scan_status: Virus scan state — ``"pending"``, ``"clean"``, or ``"infected"``.
        upload_url_expires_at: Expiry of the presigned PUT URL; ``None`` after confirmation.
        submitted_at: Set when the student confirms the upload is complete.
        user: The submitting ``User``.
        assignment: The ``Assignment`` being responded to.
    """

    __tablename__ = "assignment_submissions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_key: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    scan_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    upload_url_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    assignment: Mapped[Assignment] = relationship(
        "Assignment", foreign_keys=[assignment_id]
    )
