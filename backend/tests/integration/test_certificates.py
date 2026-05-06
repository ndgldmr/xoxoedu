"""Integration tests for certificate issuance, listing, and public verification."""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.certificate import Certificate
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.user import User


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
    local, domain = email.split("@")
    email = f"{local}_{uuid.uuid4().hex[:8]}@{domain}"
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass"),
        role=role,
        email_verified=True,
        display_name="Test Student",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_completed_enrollment(
    db: AsyncSession, student_id: uuid.UUID, instructor_id: uuid.UUID
) -> tuple[Course, Lesson]:
    course = Course(
        slug=f"cert-course-{uuid.uuid4().hex[:8]}",
        title="Certificate Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=instructor_id,
    )
    db.add(course)
    await db.flush()
    chapter = Chapter(course_id=course.id, title="Ch 1", position=1)
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
    await db.flush()

    enrollment = Enrollment(
        user_id=student_id,
        course_id=course.id,
        status="completed",
    )
    db.add(enrollment)
    db.add(LessonProgress(
        user_id=student_id,
        lesson_id=lesson.id,
        status="completed",
        watch_seconds=0,
    ))
    await db.commit()
    await db.refresh(course)
    await db.refresh(lesson)
    return course, lesson


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_certificate_for_completed_course(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /certificates/generate issues a certificate for a completed enrollment."""
    instructor, _ = await _make_user(db, f"instr-cert-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, token = await _make_user(db, f"stu-cert-{uuid.uuid4().hex[:6]}@test.com")
    course, _ = await _make_completed_enrollment(db, student.id, instructor.id)

    with patch("app.modules.certificates.tasks.generate_certificate_pdf.delay"):
        resp = await client.post(
            f"/api/v1/certificates/generate?course_id={course.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["course_id"] == str(course.id)
    assert data["verification_token"] is not None
    assert data["pdf_url"] is None  # populated later by Celery task


@pytest.mark.asyncio
async def test_generate_certificate_not_eligible(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /certificates/generate raises 422 if enrollment is not completed."""
    instructor, _ = await _make_user(db, f"instr-ne-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, token = await _make_user(db, f"stu-ne-{uuid.uuid4().hex[:6]}@test.com")

    course = Course(
        slug=f"active-course-{uuid.uuid4().hex[:8]}",
        title="Active Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=instructor.id,
    )
    db.add(course)
    await db.flush()
    db.add(Enrollment(user_id=student.id, course_id=course.id, status="active"))
    await db.commit()

    resp = await client.post(
        f"/api/v1/certificates/generate?course_id={course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_certificates(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /certificates returns the student's earned certificates."""
    instructor, _ = await _make_user(db, f"instr-list-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, token = await _make_user(db, f"stu-list-{uuid.uuid4().hex[:6]}@test.com")
    course, _ = await _make_completed_enrollment(db, student.id, instructor.id)

    import secrets
    db.add(Certificate(
        user_id=student.id,
        course_id=course.id,
        verification_token=secrets.token_urlsafe(32),
    ))
    await db.commit()

    resp = await client.get(
        "/api/v1/users/me/certificates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 1
    assert data[0]["course_id"] == str(course.id)


@pytest.mark.asyncio
async def test_verify_certificate_public(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /certificates/verify/{token} returns certificate data without authentication."""
    instructor, _ = await _make_user(db, f"instr-ver-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu-ver-{uuid.uuid4().hex[:6]}@test.com")
    course, _ = await _make_completed_enrollment(db, student.id, instructor.id)

    import secrets
    token = secrets.token_urlsafe(32)
    db.add(Certificate(
        user_id=student.id,
        course_id=course.id,
        verification_token=token,
    ))
    await db.commit()

    resp = await client.get(f"/api/v1/certificates/verify/{token}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["verification_token"] == token
    assert data["course_title"] == "Certificate Course"
    assert "student_name" in data


@pytest.mark.asyncio
async def test_verify_certificate_invalid_token(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /certificates/verify/{token} returns 404 for an unknown token."""
    resp = await client.get("/api/v1/certificates/verify/nonexistent-token-abc123")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_certificate_request(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /certificates/requests creates a pending request."""
    instructor, _ = await _make_user(db, f"instr-req-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, token = await _make_user(db, f"stu-req-{uuid.uuid4().hex[:6]}@test.com")
    course = Course(
        slug=f"req-course-{uuid.uuid4().hex[:8]}",
        title="Req Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=instructor.id,
    )
    db.add(course)
    await db.commit()

    resp = await client.post(
        f"/api/v1/certificates/requests?course_id={course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "pending"
    assert data["course_id"] == str(course.id)
