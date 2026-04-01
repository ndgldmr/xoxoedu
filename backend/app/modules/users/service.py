"""Business logic for user profile management and session administration."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, SessionNotFound
from app.db.models.session import Session
from app.db.models.user import User
from app.modules.users.schemas import UserUpdateIn


async def update_me(db: AsyncSession, user: User, body: UserUpdateIn) -> User:
    """Update profile fields for the authenticated user.

    Creates a ``UserProfile`` row on the fly if one does not yet exist (e.g.
    for OAuth-created accounts that skipped the registration form).

    Args:
        db: Async database session.
        user: The currently authenticated ``User`` ORM instance.
        body: Partial update payload; ``None`` fields are left unchanged.

    Returns:
        The refreshed ``User`` instance with updated profile data.
    """
    if not user.profile:
        from app.db.models.user import UserProfile

        profile = UserProfile(user_id=user.id)
        db.add(profile)
        await db.flush()
        await db.refresh(user)

    profile = user.profile
    if profile is None:
        raise RuntimeError("Profile should exist after flush")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(user)
    return user


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    """Return all active (non-revoked, non-expired) sessions for a user.

    Args:
        db: Async database session.
        user_id: UUID of the user whose sessions to list.

    Returns:
        A list of ``Session`` ORM instances ordered by the database default.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(Session).where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    return list(result.scalars().all())


async def revoke_session(db: AsyncSession, user: User, session_id: uuid.UUID) -> None:
    """Revoke a specific session, enforcing that the caller owns it.

    Args:
        db: Async database session.
        user: The authenticated user attempting the revocation.
        session_id: UUID of the session to revoke.

    Raises:
        SessionNotFound: If no session with that ID exists.
        Forbidden: If the session belongs to a different user.
    """
    session = await db.get(Session, session_id)
    if not session:
        raise SessionNotFound()
    if session.user_id != user.id:
        raise Forbidden()
    session.revoked_at = datetime.now(UTC)
    await db.commit()
