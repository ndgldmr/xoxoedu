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
    if not user.email_verified:
        raise EmailNotVerified()
    return user
