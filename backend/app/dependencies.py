"""Shared FastAPI dependency functions for authentication and authorization."""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailNotVerified, TokenInvalid
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
