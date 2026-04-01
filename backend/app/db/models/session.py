"""ORM model for refresh-token sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class Session(Base, UUIDMixin):
    """Persistent refresh-token session record.

    Only the SHA-256 hash of the raw refresh token is stored, so a database
    compromise does not expose live tokens.  Token rotation is enforced: each
    ``/auth/refresh`` call revokes the presented session and creates a new one.
    Replay detection: if a revoked session hash is presented, all sessions for
    that user are immediately revoked.

    Attributes:
        user_id: FK to ``users.id``; cascades on delete.
        refresh_token_hash: SHA-256 hex digest of the raw refresh token.
        expires_at: Absolute expiry timestamp (timezone-aware).
        created_at: Session creation timestamp set by the database.
        revoked_at: Set when the session is explicitly logged out, rotated,
            or invalidated by a replay attack.
        user: Back-reference to the owning ``User``.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="sessions")
