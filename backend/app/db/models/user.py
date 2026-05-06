"""ORM models for users."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import ARRAY, Boolean, Date, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.modules.users.usernames import build_default_username

if TYPE_CHECKING:
    from app.db.models.oauth_account import OAuthAccount
    from app.db.models.session import Session


def _default_username(context: Any) -> str:
    """Derive a stable fallback username for ORM inserts that omit one."""
    params = context.get_current_parameters()
    return build_default_username(
        email=params.get("email"),
        display_name=params.get("display_name"),
    )


class User(Base, UUIDMixin, TimestampMixin):
    """Core user record combining authentication identity and profile data.

    Attributes:
        email: Unique email address; used as the login identifier.
        username: Stable lowercase handle used for ``@username`` mentions.
        password_hash: bcrypt hash of the user's password, or ``None`` for
            OAuth-only accounts.
        role: Access-control role (``"student"`` or ``"admin"``).
        email_verified: Whether the user has confirmed their email address.
        display_name: Publicly visible name shown on the learner's profile.
        avatar_url: URL of the user's profile picture.
        bio: Free-form biography text.
        headline: Short professional tagline (e.g. "Full-Stack Developer").
        social_links: JSONB map of platform names to profile URLs.
        skills: Array of skill tag strings.
        sessions: Active and historical refresh-token sessions.
        oauth_accounts: Linked third-party OAuth provider accounts.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        default=_default_username,
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="student")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    social_links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gender_self_describe: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sessions: Mapped[list[Session]] = relationship("Session", back_populates="user")
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", back_populates="user"
    )
