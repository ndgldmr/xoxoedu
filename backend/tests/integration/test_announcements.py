"""Integration tests for admin announcement endpoints."""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment
from app.db.models.user import User, UserProfile


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("pass"),
        role=role,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name=email.split("@")[0]))
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course(db: AsyncSession, admin_id: uuid.UUID) -> Course:
    course = Course(
        slug=f"c-{uuid.uuid4().hex[:8]}",
        title="Announcements Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=admin_id,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_course_announcement_dispatches_emails(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /admin/announcements with scope=course enqueues task for each enrolled student."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course = await _make_course(db, admin.id)

    s1, _ = await _make_user(db, f"s1-{uuid.uuid4().hex[:4]}@x.com")
    s2, _ = await _make_user(db, f"s2-{uuid.uuid4().hex[:4]}@x.com")
    for s in [s1, s2]:
        db.add(Enrollment(user_id=s.id, course_id=course.id, status="active"))
    await db.commit()

    with patch(
        "app.modules.admin.service.send_announcement_emails.delay"
    ) as mock_delay:
        resp = await client.post(
            "/api/v1/admin/announcements",
            json={
                "title": "Week 1 Update",
                "body": "Welcome to the course!",
                "scope": "course",
                "course_id": str(course.id),
            },
            headers=_auth(token),
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Week 1 Update"
    assert data["scope"] == "course"
    assert data["sent_at"] is not None

    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args
    _, recipient_emails, _, _ = call_kwargs[0]
    assert set(recipient_emails) == {s1.email, s2.email}


@pytest.mark.asyncio
async def test_create_course_announcement_excludes_unenrolled(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Only active enrollments receive the course announcement."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course = await _make_course(db, admin.id)

    active, _ = await _make_user(db, f"active-{uuid.uuid4().hex[:4]}@x.com")
    unenrolled, _ = await _make_user(db, f"unenrolled-{uuid.uuid4().hex[:4]}@x.com")
    db.add(Enrollment(user_id=active.id, course_id=course.id, status="active"))
    db.add(Enrollment(user_id=unenrolled.id, course_id=course.id, status="unenrolled"))
    await db.commit()

    with patch(
        "app.modules.admin.service.send_announcement_emails.delay"
    ) as mock_delay:
        await client.post(
            "/api/v1/admin/announcements",
            json={
                "title": "Update",
                "body": "Hello",
                "scope": "course",
                "course_id": str(course.id),
            },
            headers=_auth(token),
        )

    _, recipient_emails, _, _ = mock_delay.call_args[0]
    assert active.email in recipient_emails
    assert unenrolled.email not in recipient_emails


@pytest.mark.asyncio
async def test_create_platform_announcement_targets_all_students(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Platform-scope announcement emails all student-role users."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    s1, _ = await _make_user(db, f"s1-{uuid.uuid4().hex[:4]}@x.com", "student")
    s2, _ = await _make_user(db, f"s2-{uuid.uuid4().hex[:4]}@x.com", "student")

    with patch(
        "app.modules.admin.service.send_announcement_emails.delay"
    ) as mock_delay:
        resp = await client.post(
            "/api/v1/admin/announcements",
            json={"title": "Platform News", "body": "Big update!", "scope": "platform"},
            headers=_auth(token),
        )

    assert resp.status_code == 201
    mock_delay.assert_called_once()
    _, recipient_emails, _, _ = mock_delay.call_args[0]
    assert s1.email in recipient_emails
    assert s2.email in recipient_emails


@pytest.mark.asyncio
async def test_create_course_announcement_without_course_id_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    """scope=course without course_id returns 500 (AppException base)."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")

    with patch("app.modules.admin.service.send_announcement_emails.delay"):
        resp = await client.post(
            "/api/v1/admin/announcements",
            json={"title": "Oops", "body": "Forgot the course.", "scope": "course"},
            headers=_auth(token),
        )
    # AppException base class maps to 500
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_list_announcements_paginated(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/announcements returns created announcements with pagination meta."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")

    with patch("app.modules.admin.service.send_announcement_emails.delay"):
        for i in range(3):
            await client.post(
                "/api/v1/admin/announcements",
                json={
                    "title": f"Announcement {i}",
                    "body": f"Body {i}",
                    "scope": "platform",
                },
                headers=_auth(token),
            )

    resp = await client.get(
        "/api/v1/admin/announcements?limit=2",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2
    assert resp.json()["meta"]["total"] >= 3


@pytest.mark.asyncio
async def test_create_announcement_invalid_scope(
    client: AsyncClient, db: AsyncSession
) -> None:
    """scope='unknown' returns 422 VALIDATION_ERROR."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Bad", "body": "Wrong scope", "scope": "unknown"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_announcement_requires_admin(client: AsyncClient, db: AsyncSession) -> None:
    """Student token cannot create or list announcements."""
    student, token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")

    resp = await client.post(
        "/api/v1/admin/announcements",
        json={"title": "Nope", "body": "Forbidden", "scope": "platform"},
        headers=_auth(token),
    )
    assert resp.status_code == 403

    resp2 = await client.get("/api/v1/admin/announcements", headers=_auth(token))
    assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_course_announcement_nonexistent_course(
    client: AsyncClient, db: AsyncSession
) -> None:
    """scope=course with a non-existent course_id returns 404."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")

    with patch("app.modules.admin.service.send_announcement_emails.delay"):
        resp = await client.post(
            "/api/v1/admin/announcements",
            json={
                "title": "Oops",
                "body": "No such course.",
                "scope": "course",
                "course_id": str(uuid.uuid4()),
            },
            headers=_auth(token),
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "COURSE_NOT_FOUND"
