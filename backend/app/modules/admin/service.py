import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserNotFound
from app.db.models.user import User


async def list_users(db: AsyncSession, skip: int, limit: int) -> tuple[list[User], int]:
    count_result = await db.execute(select(User))
    total = len(count_result.scalars().all())

    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def update_role(db: AsyncSession, user_id: uuid.UUID, role: str) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
