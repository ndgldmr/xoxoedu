"""Integration tests for assignment creation and file-upload submission flow."""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.assignment import Assignment
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.user import User

_FAKE_PRESIGNED_URL = "https://r2.example.com/fake-upload-url"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, role: str = "student"
) -> tuple[User, str]:
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


async def _make_lesson(db: AsyncSession, created_by: uuid.UUID) -> Lesson:
    course = Course(
        slug=f"course-{uuid.uuid4().hex[:8]}",
        title="Test Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.flush()
    chapter = Chapter(course_id=course.id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.flush()
    lesson = Lesson(
        chapter_id=chapter.id,
        title="Lesson 1",
        position=1,
        type="video",
        is_free_preview=False,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_assignment(
    db: AsyncSession,
    lesson_id: uuid.UUID,
    allowed_extensions: list[str] | None = None,
) -> Assignment:
    assignment = Assignment(
        lesson_id=lesson_id,
        title="Test Assignment",
        instructions="Submit your work.",
        allowed_extensions=allowed_extensions or ["pdf", "docx"],
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_assignment_admin_ok(client: AsyncClient, db: AsyncSession) -> None:
    """Admin can create an assignment on a lesson."""
    admin, token = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    lesson = await _make_lesson(db, admin.id)

    payload = {
        "lesson_id": str(lesson.id),
        "title": "Final Project",
        "instructions": "Write a report.",
        "allowed_extensions": ["pdf"],
    }
    resp = await client.post(
        "/api/v1/admin/assignments", json=payload, headers=_auth(token)
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Final Project"
    assert data["allowed_extensions"] == ["pdf"]


@pytest.mark.asyncio
async def test_create_assignment_student_forbidden(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    payload = {
        "lesson_id": str(uuid.uuid4()),
        "title": "Bad",
        "instructions": ".",
    }
    resp = await client.post(
        "/api/v1/admin/assignments", json=payload, headers=_auth(token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_request_upload_returns_presigned_url(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /assignments/{id}/upload returns a presigned URL and submission_id."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    assignment = await _make_assignment(db, lesson.id)

    with patch(
        "app.modules.assignments.service.generate_presigned_put",
        return_value=_FAKE_PRESIGNED_URL,
    ):
        resp = await client.post(
            f"/api/v1/assignments/{assignment.id}/upload",
            json={
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 1024,
            },
            headers=_auth(s_token),
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["upload_url"] == _FAKE_PRESIGNED_URL
    assert "submission_id" in data
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_confirm_upload_sets_submitted_at(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /assignments/submissions/{id}/confirm stamps submitted_at."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    assignment = await _make_assignment(db, lesson.id)

    with patch(
        "app.modules.assignments.service.generate_presigned_put",
        return_value=_FAKE_PRESIGNED_URL,
    ):
        upload_resp = await client.post(
            f"/api/v1/assignments/{assignment.id}/upload",
            json={
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 512,
            },
            headers=_auth(s_token),
        )

    submission_id = upload_resp.json()["data"]["submission_id"]

    confirm_resp = await client.post(
        f"/api/v1/assignments/submissions/{submission_id}/confirm",
        headers=_auth(s_token),
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["data"]["submitted_at"] is not None


@pytest.mark.asyncio
async def test_list_submissions_student(client: AsyncClient, db: AsyncSession) -> None:
    """GET /assignments/{id}/submissions returns submissions for the student."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    assignment = await _make_assignment(db, lesson.id)

    with patch(
        "app.modules.assignments.service.generate_presigned_put",
        return_value=_FAKE_PRESIGNED_URL,
    ):
        await client.post(
            f"/api/v1/assignments/{assignment.id}/upload",
            json={
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 256,
            },
            headers=_auth(s_token),
        )

    resp = await client.get(
        f"/api/v1/assignments/{assignment.id}/submissions",
        headers=_auth(s_token),
    )
    assert resp.status_code == 200
    submissions = resp.json()["data"]
    assert len(submissions) == 1
    assert submissions[0]["file_name"] == "report.pdf"
    assert submissions[0]["scan_status"] == "pending"


@pytest.mark.asyncio
async def test_upload_rejects_invalid_extension(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Uploading a disallowed file extension returns a 500 validation error."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    assignment = await _make_assignment(db, lesson.id, allowed_extensions=["pdf"])

    with patch(
        "app.modules.assignments.service.generate_presigned_put",
        return_value=_FAKE_PRESIGNED_URL,
    ):
        resp = await client.post(
            f"/api/v1/assignments/{assignment.id}/upload",
            json={
                "file_name": "malware.exe",
                "mime_type": "application/octet-stream",
                "file_size": 1024,
            },
            headers=_auth(s_token),
        )
    assert resp.status_code == 500  # AppException base class, status 500
