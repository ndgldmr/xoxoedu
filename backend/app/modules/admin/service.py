"""Business logic for admin user and course management operations."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserNotFound
from app.db.models.user import User


async def list_users(db: AsyncSession, skip: int, limit: int) -> tuple[list[User], int]:
    """Return a paginated list of all users with the total count.

    Args:
        db: Async database session.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(users, total)`` where ``total`` is the unfiltered row count.
    """
    count_result = await db.execute(select(User))
    total = len(count_result.scalars().all())

    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def update_role(db: AsyncSession, user_id: uuid.UUID, role: str) -> User:
    """Change the role of a user by ID.

    Args:
        db: Async database session.
        user_id: UUID of the user to update.
        role: The new role string (e.g. ``"admin"``, ``"instructor"``, ``"student"``).

    Returns:
        The updated ``User`` ORM instance.

    Raises:
        UserNotFound: If no user with that ID exists.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Hard-delete a user record by ID.

    Args:
        db: Async database session.
        user_id: UUID of the user to delete.

    Raises:
        UserNotFound: If no user with that ID exists.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
