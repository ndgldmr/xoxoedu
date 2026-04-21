import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import User


async def _login(client: AsyncClient, db: AsyncSession, email: str) -> str:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass123"),
        role="student",
        email_verified=True,
        display_name="Test",
    )
    db.add(user)
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 200
    return str(resp.cookies.get("refresh_token"))


@pytest.mark.asyncio
async def test_refresh_returns_new_token(client: AsyncClient, db: AsyncSession) -> None:
    await _login(client, db, "refresh1@example.com")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    assert "access_token" in resp.json()["data"]
    assert resp.cookies.get("refresh_token") is not None


@pytest.mark.asyncio
async def test_refresh_without_cookie_fails(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_refresh_replay_revokes_all_sessions(client: AsyncClient, db: AsyncSession) -> None:
    raw_token = await _login(client, db, "replay@example.com")

    # First refresh — legitimate
    client.cookies.set("refresh_token", raw_token)
    resp1 = await client.post("/api/v1/auth/refresh")
    assert resp1.status_code == 200

    # Use original token again — replay
    client.cookies.set("refresh_token", raw_token)
    resp2 = await client.post("/api/v1/auth/refresh")
    assert resp2.status_code == 401
    assert resp2.json()["error"]["code"] == "REFRESH_TOKEN_REPLAYED"
