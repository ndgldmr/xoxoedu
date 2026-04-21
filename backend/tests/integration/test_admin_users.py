import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.user import User


async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass123"),
        role=role,
        email_verified=True,
        display_name=email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


@pytest.mark.asyncio
async def test_list_users_as_admin(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin-list@example.com", role="admin")
    await _make_user(db, "student-list@example.com")

    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 2
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_list_users_forbidden_for_student(client: AsyncClient, db: AsyncSession) -> None:
    _, student_token = await _make_user(db, "student-forbidden@example.com")
    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {student_token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_users_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_role_promote_to_admin(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin-promote@example.com", role="admin")
    student, _ = await _make_user(db, "student-promote@example.com")

    resp = await client.patch(
        f"/api/v1/admin/users/{student.id}/role",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "admin"


@pytest.mark.asyncio
async def test_update_role_demote_to_student(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin-demote@example.com", role="admin")
    other_admin, _ = await _make_user(db, "other-admin-demote@example.com", role="admin")

    resp = await client.patch(
        f"/api/v1/admin/users/{other_admin.id}/role",
        json={"role": "student"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "student"


@pytest.mark.asyncio
async def test_update_role_not_found(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin-notfound@example.com", role="admin")
    resp = await client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}/role",
        json={"role": "student"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_user(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin-del@example.com", role="admin")
    target, _ = await _make_user(db, "target-del@example.com")

    resp = await client.delete(
        f"/api/v1/admin/users/{target.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204

    # Confirm the user is gone from the list
    list_resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    ids = [u["id"] for u in list_resp.json()["data"]]
    assert str(target.id) not in ids


@pytest.mark.asyncio
async def test_delete_user_not_found(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin-delnf@example.com", role="admin")
    resp = await client.delete(
        f"/api/v1/admin/users/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
