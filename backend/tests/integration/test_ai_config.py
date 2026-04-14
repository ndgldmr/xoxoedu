"""Integration tests for admin AI config CRUD endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Course
from app.db.models.user import User, UserProfile


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, role: str = "student"
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass"),
        role=role,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name="Test User"))
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course(db: AsyncSession, created_by: uuid.UUID) -> Course:
    course = Course(
        slug=f"ai-course-{uuid.uuid4().hex[:8]}",
        title="AI Test Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


# ── GET /admin/ai/config/{course_id} ──────────────────────────────────────────

async def test_get_config_returns_defaults_when_no_row_exists(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET returns platform defaults without creating a row."""
    admin, token = await _make_user(db, "admin-ai-get@example.com", role="admin")
    course = await _make_course(db, admin.id)

    resp = await client.get(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["course_id"] == str(course.id)
    assert data["ai_enabled"] is True
    assert data["tone"] == "encouraging"
    assert data["system_prompt_override"] is None
    assert data["monthly_token_limit"] > 0
    assert 0.0 < data["alert_threshold"] <= 1.0


async def test_get_config_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Students cannot access AI config endpoints."""
    student, token = await _make_user(db, "student-ai@example.com", role="student")
    course = await _make_course(db, student.id)

    resp = await client.get(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── PATCH /admin/ai/config/{course_id} ────────────────────────────────────────

async def test_patch_config_creates_row(
    client: AsyncClient, db: AsyncSession
) -> None:
    """First PATCH creates a config row with the supplied values."""
    admin, token = await _make_user(db, "admin-ai-patch@example.com", role="admin")
    course = await _make_course(db, admin.id)

    resp = await client.patch(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        json={"tone": "strict", "monthly_token_limit": 50_000},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["tone"] == "strict"
    assert data["monthly_token_limit"] == 50_000
    # Unset fields retain defaults
    assert data["ai_enabled"] is True


async def test_patch_config_updates_existing_row(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Subsequent PATCHes update the existing row."""
    admin, token = await _make_user(db, "admin-ai-update@example.com", role="admin")
    course = await _make_course(db, admin.id)

    # Create
    await client.patch(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        json={"tone": "neutral"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Update
    resp = await client.patch(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        json={"ai_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["ai_enabled"] is False
    assert data["tone"] == "neutral"  # previous value preserved


async def test_patch_config_get_reflects_persisted_values(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET after PATCH returns the stored values, not defaults."""
    admin, token = await _make_user(db, "admin-ai-roundtrip@example.com", role="admin")
    course = await _make_course(db, admin.id)

    await client.patch(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        json={"tone": "strict", "alert_threshold": 0.5},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()["data"]
    assert data["tone"] == "strict"
    assert data["alert_threshold"] == pytest.approx(0.5)


async def test_patch_invalid_tone_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Invalid tone values are rejected with 422."""
    admin, token = await _make_user(db, "admin-ai-badtone@example.com", role="admin")
    course = await _make_course(db, admin.id)

    resp = await client.patch(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        json={"tone": "aggressive"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_patch_config_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, "student-ai-patch@example.com", role="student")
    course = await _make_course(db, student.id)

    resp = await client.patch(
        f"/api/v1/ai/admin/ai/config/{course.id}",
        json={"ai_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
