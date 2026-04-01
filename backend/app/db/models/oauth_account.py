"""ORM model for third-party OAuth provider account links."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class OAuthAccount(Base, UUIDMixin):
    """Link between a platform user and a third-party OAuth provider identity.

    The ``(provider, provider_user_id)`` pair is unique, preventing duplicate
    accounts if the same provider identity is presented twice.

    Attributes:
        user_id: FK to ``users.id``; cascades on delete.
        provider: OAuth provider name (e.g. ``"google"``).
        provider_user_id: The user's stable ID in the provider's system.
        access_token_enc: Optionally stored (encrypted) provider access token
            for future API calls on behalf of the user.
        user: Back-reference to the owning ``User``.
    """

    __tablename__ = "oauth_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    user: Mapped[User] = relationship("User", back_populates="oauth_accounts")
