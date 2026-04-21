
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import User


async def _create_verified_user(db: AsyncSession, email: str, password: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        role="student",
        email_verified=True,
        display_name="Test User",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db: AsyncSession) -> None:
    await _create_verified_user(db, "login@example.com", "securepass")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "securepass"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access_token" in data
    assert resp.cookies.get("refresh_token") is not None


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, db: AsyncSession) -> None:
    await _create_verified_user(db, "wrongpass@example.com", "correctpass")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpass@example.com", "password": "wrongpass"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anypassword"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"
