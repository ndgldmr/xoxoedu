import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User

MOCK_USERINFO = {
    "sub": "google-uid-12345",
    "email": "oauthuser@gmail.com",
    "name": "OAuth User",
    "picture": "https://example.com/photo.jpg",
}

MOCK_TOKEN = {
    "access_token": "ya29.mock_token",
    "userinfo": MOCK_USERINFO,
}


@pytest.mark.asyncio
async def test_oauth_callback_creates_new_user(client: AsyncClient, db: AsyncSession) -> None:
    with patch(
        "app.modules.auth.router.google_get_token",
        new=AsyncMock(return_value=MOCK_TOKEN),
    ):
        resp = await client.get("/api/v1/auth/google/callback", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?oauth=success"

    created_user = await db.scalar(select(User).where(User.email == "oauthuser@gmail.com"))
    assert created_user is not None
    assert created_user.email_verified is True
    assert created_user.avatar_url is None


@pytest.mark.asyncio
async def test_oauth_callback_links_existing_email(client: AsyncClient, db: AsyncSession) -> None:
    # Pre-create a user with the same email
    user = User(
        id=uuid.uuid4(),
        email="oauthexisting@gmail.com",
        password_hash=None,
        role="student",
        email_verified=False,
        display_name="Existing",
    )
    db.add(user)
    await db.commit()

    mock_token = {
        "access_token": "ya29.mock",
        "userinfo": {**MOCK_USERINFO, "sub": "google-uid-999", "email": "oauthexisting@gmail.com"},
    }
    with patch(
        "app.modules.auth.router.google_get_token",
        new=AsyncMock(return_value=mock_token),
    ):
        resp = await client.get("/api/v1/auth/google/callback", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?oauth=success"
    # Should not create a duplicate user
    count = await db.scalar(
        select(func.count()).where(User.email == "oauthexisting@gmail.com")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_oauth_callback_existing_oauth_account(client: AsyncClient, db: AsyncSession) -> None:
    mock_token = {
        "access_token": "ya29.mock2",
        "userinfo": {**MOCK_USERINFO, "sub": "google-uid-repeat", "email": "repeat@gmail.com"},
    }
    with patch(
        "app.modules.auth.router.google_get_token",
        new=AsyncMock(return_value=mock_token),
    ):
        resp1 = await client.get("/api/v1/auth/google/callback", follow_redirects=False)
        resp2 = await client.get("/api/v1/auth/google/callback", follow_redirects=False)

    assert resp1.status_code == 302
    assert resp2.status_code == 302
    assert resp1.headers["location"] == "/login?oauth=success"
    assert resp2.headers["location"] == "/login?oauth=success"

    count = await db.scalar(select(func.count()).where(User.email == "repeat@gmail.com"))
    assert count == 1


@pytest.mark.asyncio
async def test_oauth_callback_redirects_to_error_on_provider_failure(client: AsyncClient) -> None:
    with patch(
        "app.modules.auth.router.google_get_token",
        new=AsyncMock(side_effect=RuntimeError("oauth failed")),
    ):
        resp = await client.get("/api/v1/auth/google/callback", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?oauth=error"
