"""ORM models for certificates and certificate requests."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course
    from app.db.models.user import User


class Certificate(Base, UUIDMixin):
    """An earned certificate for completing a course.

    Attributes:
        user_id: The student who earned the certificate.
        course_id: The course the certificate was issued for.
        verification_token: Unique URL-safe token for public certificate verification.
        issued_at: When the certificate was issued (set by the database).
        pdf_url: R2/S3 URL to the generated PDF; ``None`` until the Celery task completes.
    """

    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_certificates_user_course"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verification_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])


class CertificateRequest(Base, UUIDMixin):
    """A student's request for manual certificate review.

    Attributes:
        user_id: The student requesting the certificate.
        course_id: The course for which the certificate is requested.
        status: Current review state — ``pending``, ``approved``, or ``rejected``.
        requested_at: When the request was submitted.
        reviewed_by: UUID of the admin who reviewed the request; ``None`` if pending.
        reviewed_at: When the admin acted on the request; ``None`` if pending.
    """

    __tablename__ = "certificate_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])
