"""ORM model for live session attendance records."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.live_session import LiveSession
    from app.db.models.user import User


class SessionAttendance(Base, UUIDMixin, TimestampMixin):
    """Attendance record for a single student at a single live session.

    One row per ``(session_id, user_id)`` pair — the unique constraint
    enforces this at the database level.  Writes are idempotent: marking
    attendance a second time updates the existing row's ``status`` and
    ``updated_at`` rather than creating a duplicate.

    Status lifecycle:
        - ``present`` — student attended.
        - ``absent`` — student did not attend.
        - ``late`` — student attended but arrived late.

    Attendance writes are allowed at any time (including after the session
    ends) so that staff can backfill missing records.

    Attributes:
        session_id: FK to the parent live session; cascades on session delete.
        user_id: FK to the student; cascades on user delete.
        status: Attendance status — ``"present"``, ``"absent"``, or ``"late"``.
        session: The parent ``LiveSession`` ORM relationship.
        user: The ``User`` ORM relationship.
    """

    __tablename__ = "session_attendance"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "user_id", name="uq_session_attendance_session_user"
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    session: Mapped[LiveSession] = relationship(
        "LiveSession", foreign_keys=[session_id]
    )
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
