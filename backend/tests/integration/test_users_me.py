import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.user import User


async def _make_user_and_token(db: AsyncSession, email: str) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass123"),
        role="student",
        email_verified=True,
        display_name="Test User",
        avatar_url="https://cdn.example.com/avatar.png",
        date_of_birth=date(2000, 1, 2),
        country="BR",
        gender="female",
    )
    db.add(user)
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
    assert data["display_name"] == "Test User"
    assert data["profile_complete"] is True


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_me(client: AsyncClient, db: AsyncSession) -> None:
    user, token = await _make_user_and_token(db, "patch@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={
            "display_name": "Updated Name",
            "bio": "My bio",
            "social_links": {"website": "https://example.com"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["display_name"] == "Updated Name"
    assert data["bio"] == "My bio"
    assert data["social_links"]["website"] == "https://example.com/"


@pytest.mark.asyncio
async def test_get_me_normalizes_legacy_gender_values(client: AsyncClient, db: AsyncSession) -> None:
    user, token = await _make_user_and_token(db, "legacy-gender@example.com")
    user.gender = "self_describe"
    user.gender_self_describe = "Agender"
    await db.commit()
    await db.refresh(user)

    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["gender"] == "other"
    assert data["gender_self_describe"] is None
    assert data["profile_complete"] is True


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
