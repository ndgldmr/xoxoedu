"""ORM models for users and their public-facing profiles."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.oauth_account import OAuthAccount
    from app.db.models.session import Session


class User(Base, UUIDMixin, TimestampMixin):
    """Core authentication record for a platform user.

    Attributes:
        email: Unique email address; used as the login identifier.
        password_hash: bcrypt hash of the user's password, or ``None`` for
            OAuth-only accounts.
        role: Access-control role (``"student"`` or ``"admin"``).
        email_verified: Whether the user has confirmed their email address.
        profile: One-to-one ``UserProfile`` loaded eagerly via ``selectin``.
        sessions: Active and historical refresh-token sessions.
        oauth_accounts: Linked third-party OAuth provider accounts.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="student")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    profile: Mapped[UserProfile | None] = relationship(
        "UserProfile", back_populates="user", uselist=False, lazy="selectin"
    )
    sessions: Mapped[list[Session]] = relationship("Session", back_populates="user")
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", back_populates="user"
    )


class UserProfile(Base):
    """Extended public-facing profile data for a user.

    Stored in a separate table so the core ``users`` table stays lean.
    The primary key ``user_id`` doubles as the foreign key, enforcing a
    strict one-to-one relationship with CASCADE delete.

    Attributes:
        user_id: FK to ``users.id``; also the primary key of this table.
        display_name: Publicly visible name shown on the learner's profile.
        avatar_url: URL of the user's profile picture.
        bio: Free-form biography text.
        headline: Short professional tagline (e.g. "Full-Stack Developer").
        social_links: JSONB map of platform names to profile URLs.
        skills: Array of skill tag strings.
        user: Back-reference to the owning ``User`` row.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    social_links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="profile")
