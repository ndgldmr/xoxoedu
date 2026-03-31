import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.user import User, UserProfile


async def _make_user_and_token(db: AsyncSession, email: str) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass123"),
        role="student",
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name="Test User"))
    await db.commit()
    await db.refresh(user)
    token = create_access_token(str(user.id), user.role)
    return user, token


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, db: AsyncSession) -> None:
    user, token = await _make_user_and_token(db, "me@example.com")
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == "me@example.com"
    assert data["profile"]["display_name"] == "Test User"


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_me(client: AsyncClient, db: AsyncSession) -> None:
    user, token = await _make_user_and_token(db, "patch@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"display_name": "Updated Name", "bio": "My bio"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["profile"]["display_name"] == "Updated Name"
    assert data["profile"]["bio"] == "My bio"


@pytest.mark.asyncio
async def test_list_and_revoke_sessions(client: AsyncClient, db: AsyncSession) -> None:
    user, token = await _make_user_and_token(db, "sessions@example.com")

    # Login to create a session
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "sessions@example.com", "password": "testpass123"},
    )
    assert login_resp.status_code == 200

    sessions_resp = await client.get(
        "/api/v1/users/me/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()["data"]
    assert len(sessions) >= 1

    session_id = sessions[0]["id"]
    revoke_resp = await client.delete(
        f"/api/v1/users/me/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoke_resp.status_code == 204
