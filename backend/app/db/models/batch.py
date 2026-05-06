"""ORM models for cohort batches, batch enrollments, and batch transfer requests."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.program import Program, ProgramEnrollment
    from app.db.models.user import User


class Batch(Base, UUIDMixin, TimestampMixin):
    """A scheduled cohort run of a program.

    A batch is a time-bounded, capacity-limited group of students going through
    the same program together.  Multiple batches can exist for a single program
    (e.g. one per term), but a student may belong to at most one *active* batch
    at any given time.

    Batches belong to a ``Program``, not a ``Course``.  The default capacity
    is ``15`` seats, which is the launch cohort limit for XOXO Education.

    Status lifecycle: ``upcoming`` → ``active`` → ``archived``.  The
    ``upcoming`` status can also transition directly to ``archived`` to cancel
    a batch before it starts.  Archived batches become read-only — no new
    membership writes are accepted and status cannot change further.

    Dates are always stored in UTC.  The separate ``timezone`` column holds the
    canonical IANA timezone name used for display and scheduling logic.

    Attributes:
        program_id: FK to the parent program; cascades on program delete.
        title: Human-readable cohort label (e.g. ``"Spring 2026 Cohort"``).
        status: Lifecycle state: ``"upcoming"``, ``"active"``, or ``"archived"``.
        timezone: IANA timezone name (e.g. ``"America/New_York"``).
        starts_at: UTC timestamp when the cohort's learning period begins.
        ends_at: UTC timestamp when the cohort's learning period ends.
        enrollment_opens_at: UTC timestamp when students may start joining; nullable.
        enrollment_closes_at: UTC timestamp after which no new members are accepted; nullable.
        capacity: Maximum seat count; defaults to 15.
        program: The parent ``Program``.
        members: All ``BatchEnrollment`` records for this batch.
        transfer_requests_from: Transfer requests where this batch is the origin.
        transfer_requests_to: Transfer requests where this batch is the target.
    """

    __tablename__ = "batches"

    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="upcoming")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enrollment_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enrollment_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")

    program: Mapped[Program] = relationship("Program", foreign_keys=[program_id])
    members: Mapped[list[BatchEnrollment]] = relationship(
        "BatchEnrollment", back_populates="batch"
    )
    transfer_requests_from: Mapped[list[BatchTransferRequest]] = relationship(
        "BatchTransferRequest",
        foreign_keys="BatchTransferRequest.from_batch_id",
        back_populates="from_batch",
    )
    transfer_requests_to: Mapped[list[BatchTransferRequest]] = relationship(
        "BatchTransferRequest",
        foreign_keys="BatchTransferRequest.to_batch_id",
        back_populates="to_batch",
    )


class BatchEnrollment(Base, UUIDMixin):
    """Membership record linking a student to a specific batch.

    Anchored to the student's ``ProgramEnrollment`` rather than a course-level
    ``Enrollment``.  Batch membership represents live cohort placement and does
    not affect academic progress state — ``LessonProgress``, course completion,
    and certificates are unaffected by batch changes.

    The unique constraint on ``(batch_id, user_id)`` prevents a student from
    being added twice to the same batch.

    Attributes:
        batch_id: FK to the parent batch; cascades on batch delete.
        user_id: FK to the enrolled student; cascades on user delete.
        program_enrollment_id: FK to the student's program enrollment;
            cascades on delete.
        enrolled_at: UTC timestamp set by the database when the row is inserted.
        batch: The parent ``Batch``.
        user: The enrolled ``User``.
        program_enrollment: The student's ``ProgramEnrollment``.
    """

    __tablename__ = "batch_enrollments"
    __table_args__ = (
        UniqueConstraint("batch_id", "user_id", name="uq_batch_enrollments_batch_user"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("program_enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    batch: Mapped[Batch] = relationship("Batch", back_populates="members")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    program_enrollment: Mapped[ProgramEnrollment] = relationship(
        "ProgramEnrollment", foreign_keys=[program_enrollment_id]
    )


class BatchTransferRequest(Base, UUIDMixin, TimestampMixin):
    """Formal student request to transfer from one batch to another.

    Approval moves batch membership to the target batch without resetting any
    academic progress — ``LessonProgress``, course completion state, certificates,
    and ``ProgramEnrollment`` state are all preserved on approval.

    Both batch FKs use ``SET NULL`` on delete so that historical transfer
    records survive if a batch is later archived or removed.

    Status lifecycle: ``pending`` → ``approved`` or ``denied``; any status →
    ``canceled`` (student-initiated).  Approved and denied are terminal admin
    states.

    Attributes:
        user_id: FK to the requesting student.
        from_batch_id: FK to the student's current batch at request time.
        to_batch_id: FK to the requested target batch.
        status: Workflow state: ``pending``, ``approved``, ``denied``,
            ``canceled``.
        reason: Optional free-text reason provided by the student.
        reviewed_by: FK to the admin who processed the request; nullable until
            reviewed.
        reviewed_at: UTC timestamp of admin review.
        user: The requesting ``User``.
        from_batch: The origin ``Batch``.
        to_batch: The target ``Batch``.
        reviewer: The admin ``User`` who reviewed the request.
    """

    __tablename__ = "batch_transfer_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    from_batch: Mapped[Batch | None] = relationship(
        "Batch", foreign_keys=[from_batch_id], back_populates="transfer_requests_from"
    )
    to_batch: Mapped[Batch | None] = relationship(
        "Batch", foreign_keys=[to_batch_id], back_populates="transfer_requests_to"
    )
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])
