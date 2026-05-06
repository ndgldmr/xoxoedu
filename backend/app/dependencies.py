"""Shared FastAPI dependency functions for authentication and authorization."""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailNotVerified, SubscriptionRequired, TokenInvalid
from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the Bearer token and return the corresponding User row.

    Args:
        credentials: HTTP Bearer credentials extracted by ``HTTPBearer``.
        db: Async database session injected by ``get_db``.

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        TokenInvalid: If no token is provided, the token cannot be decoded,
            or no user exists for the ``sub`` claim.
    """
    token = credentials.credentials if credentials else None
    if not token:
        raise TokenInvalid()

    payload = decode_access_token(token)
    user = await db.get(User, uuid.UUID(str(payload["sub"])))
    if not user:
        raise TokenInvalid()
    return user


async def get_current_verified_user(
    user: User = Depends(get_current_user),
) -> User:
    """Extend ``get_current_user`` to require a verified email address.

    Args:
        user: User returned by ``get_current_user``.

    Returns:
        The same ``User`` instance if their email is verified.

    Raises:
        EmailNotVerified: If the user has not confirmed their email address.
    """
    if not user.email_verified:
        raise EmailNotVerified()
    return user


async def _active_subscription_guard(
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require the authenticated student to have an active or trialing subscription.

    Used as a route or router-level dependency to gate content access on
    subscription state rather than course purchase history.

    Args:
        current_user: Verified ``User`` from ``get_current_verified_user``.
        db: Async database session.

    Returns:
        The same ``User`` instance if they hold an active subscription.

    Raises:
        SubscriptionRequired: If the user has no active or trialing subscription
            (status 402).
    """
    from app.db.models.subscription import Subscription

    row = await db.scalar(
        select(Subscription).where(
            Subscription.user_id == current_user.id,
            Subscription.status.in_(["active", "trialing"]),
        ).limit(1)
    )
    if row is None:
        raise SubscriptionRequired()
    return current_user


require_active_subscription = Depends(_active_subscription_guard)
