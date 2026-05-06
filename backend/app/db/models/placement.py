"""ORM models for placement attempts and placement results."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.program import Program
    from app.db.models.user import User


class PlacementAttempt(Base, UUIDMixin, TimestampMixin):
    """One completed student attempt at the English placement assessment.

    Stores answers, timing information, raw scoring inputs, and execution
    metadata.  A student may have multiple attempts (e.g. if an admin resets
    placement), but only one ``PlacementResult`` is authoritative at any time.

    ``completed_at`` is ``None`` while the attempt is still in progress and is
    set when the student submits.  Abandoned in-progress attempts may be cleaned
    up by a background job.

    Attributes:
        user_id: FK to the student who took the assessment.
        answers: JSONB map of question identifiers to selected answer values.
        score: Computed numeric score; ``None`` while scoring is pending.
        started_at: UTC timestamp when the student began the assessment.
        completed_at: UTC timestamp when the student submitted.
        meta: Optional execution metadata (e.g. assessment version, timing per
            question).
        user: The ``User`` who took this attempt.
        result: The ``PlacementResult`` derived from this attempt, if any.
    """

    __tablename__ = "placement_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    result: Mapped[PlacementResult | None] = relationship(
        "PlacementResult", back_populates="attempt", uselist=False
    )


class PlacementResult(Base, UUIDMixin, TimestampMixin):
    """Normalized output of a placement attempt or admin assignment.

    Assigns the target program and stores any confidence/level metadata needed
    later.  When ``is_override`` is ``True``, the record represents a manual
    admin assignment and ``attempt_id`` may be ``None``.

    ``program_id`` uses ``SET NULL`` on delete so that historical result records
    survive if a program is later archived or removed.

    Attributes:
        user_id: FK to the assessed student.
        attempt_id: FK to the ``PlacementAttempt`` this result was derived from;
            ``None`` for admin overrides.
        program_id: FK to the assigned ``Program``; ``None`` if the program was
            later removed (historical preservation).
        level: Optional band or confidence label (e.g. ``"A2"``, ``"B1"``).
        is_override: ``True`` when set by an admin rather than derived from an
            attempt.
        assigned_at: DB-set timestamp when the result row was created.
        user: The ``User`` who was assessed.
        attempt: The ``PlacementAttempt`` this result came from, if any.
        program: The assigned ``Program``, if still present.
    """

    __tablename__ = "placement_results"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("placement_attempts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    attempt: Mapped[PlacementAttempt | None] = relationship(
        "PlacementAttempt", back_populates="result", foreign_keys=[attempt_id]
    )
    program: Mapped[Program | None] = relationship("Program", foreign_keys=[program_id])
