import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import User, UserProfile


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient, db: AsyncSession) -> None:
    user = User(
        id=uuid.uuid4(),
        email="logout@example.com",
        password_hash=hash_password("testpass123"),
        role="student",
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name="Test"))
    await db.commit()

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "logout@example.com", "password": "testpass123"},
    )
    assert login_resp.status_code == 200

    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 204

    # Refresh should now fail
    refresh_resp = await client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code in (400, 401)
