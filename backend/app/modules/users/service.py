import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, SessionNotFound
from app.db.models.session import Session
from app.db.models.user import User
from app.modules.users.schemas import UserUpdateIn


async def update_me(db: AsyncSession, user: User, body: UserUpdateIn) -> User:
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
    session = await db.get(Session, session_id)
    if not session:
        raise SessionNotFound()
    if session.user_id != user.id:
        raise Forbidden()
    session.revoked_at = datetime.now(UTC)
    await db.commit()
