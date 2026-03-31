import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_email_token, hash_password
from app.db.models.user import User, UserProfile


@pytest.mark.asyncio
async def test_forgot_password_silent_for_unknown_email(client: AsyncClient) -> None:
    with patch("app.modules.auth.tasks.send_password_reset_email.delay") as mock_task:
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
    assert resp.status_code == 202
    mock_task.assert_not_called()


@pytest.mark.asyncio
async def test_forgot_password_sends_email(client: AsyncClient, db: AsyncSession) -> None:
    user = User(
        id=uuid.uuid4(),
        email="reset@example.com",
        password_hash=hash_password("oldpass123"),
        role="student",
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name="Reset"))
    await db.commit()

    with patch("app.modules.auth.tasks.send_password_reset_email.delay") as mock_task:
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "reset@example.com"},
        )
    assert resp.status_code == 202
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_reset_password_changes_password(client: AsyncClient, db: AsyncSession) -> None:
    user = User(
        id=uuid.uuid4(),
        email="doreset@example.com",
        password_hash=hash_password("oldpass123"),
        role="student",
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name="DoReset"))
    await db.commit()

    token = create_email_token("doreset@example.com", purpose="reset")
    resp = await client.post(
        f"/api/v1/auth/reset-password/{token}",
        json={"password": "newpass456"},
    )
    assert resp.status_code == 200

    # Old password should no longer work
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "doreset@example.com", "password": "oldpass123"},
    )
    assert login_resp.status_code == 401

    # New password should work
    login_resp2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "doreset@example.com", "password": "newpass456"},
    )
    assert login_resp2.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_invalid_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/reset-password/invalid-token",
        json={"password": "newpass456"},
    )
    assert resp.status_code == 400
