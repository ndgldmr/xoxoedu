"""Integration tests for AL-BE-7 — program/lesson unlock engine.

Covers:
  - GET /api/v1/users/me/program-progress
  - save_progress unlock gate (POST /api/v1/lessons/{id}/progress)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.user import User


# ── Fixture helpers ────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession,
    email: str,
    *,
    role: str = "student",
) -> tuple[User, str]:
    local, domain = email.split("@")
    email = f"{local}_{uuid.uuid4().hex[:8]}@{domain}"
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=f"user_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("testpass123"),
        role=role,
        email_verified=True,
        display_name=email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_program(db: AsyncSession) -> Program:
    program = Program(
        code=f"P{uuid.uuid4().hex[:5].upper()}",
        title="Test Program",
        is_active=True,
    )
    db.add(program)
    await db.commit()
    await db.refresh(program)
    return program


async def _make_course(db: AsyncSession) -> Course:
    course = Course(
        title=f"Course {uuid.uuid4().hex[:6]}",
        slug=uuid.uuid4().hex[:12],
        status="published",
        price_cents=0,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_chapter(
    db: AsyncSession, course_id: uuid.UUID, position: int = 1
) -> Chapter:
    chapter = Chapter(course_id=course_id, title=f"Chapter {position}", position=position)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def _make_lesson(
    db: AsyncSession,
    chapter_id: uuid.UUID,
    position: int = 1,
    *,
    is_locked: bool = False,
) -> Lesson:
    lesson = Lesson(
        chapter_id=chapter_id,
        title=f"Lesson {position}",
        type="text",
        position=position,
        is_locked=is_locked,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_program_step(
    db: AsyncSession,
    program_id: uuid.UUID,
    course_id: uuid.UUID,
    position: int,
    *,
    is_required: bool = True,
) -> ProgramStep:
    step = ProgramStep(
        program_id=program_id,
        course_id=course_id,
        position=position,
        is_required=is_required,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


async def _make_program_enrollment(
    db: AsyncSession, user_id: uuid.UUID, program_id: uuid.UUID
) -> ProgramEnrollment:
    pe = ProgramEnrollment(user_id=user_id, program_id=program_id, status="active")
    db.add(pe)
    await db.commit()
    await db.refresh(pe)
    return pe


async def _make_enrollment(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    status: str = "active",
) -> Enrollment:
    enrollment = Enrollment(user_id=user_id, course_id=course_id, status=status)
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def _make_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
    status: str = "completed",
) -> LessonProgress:
    from datetime import UTC, datetime
    progress = LessonProgress(
        user_id=user_id,
        lesson_id=lesson_id,
        status=status,
        watch_seconds=0,
        completed_at=datetime.now(UTC) if status == "completed" else None,
    )
    db.add(progress)
    await db.commit()
    await db.refresh(progress)
    return progress


# ── GET /users/me/program-progress ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_active_program_returns_403(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, f"noprog-{uuid.uuid4().hex[:6]}@example.com")
    resp = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PROGRAM_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(
    client: AsyncClient, db: AsyncSession
) -> None:
    resp = await client.get("/api/v1/users/me/program-progress")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_initial_state_first_lesson_only_accessible(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"pp-init-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    await _make_lesson(db, chapter.id, 1)
    await _make_lesson(db, chapter.id, 2)

    resp = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_steps"] == 1
    assert data["completed_steps"] == 0
    lessons = data["current_step"]["lessons"]
    assert len(lessons) == 2
    assert lessons[0]["is_accessible"] is True
    assert lessons[1]["is_accessible"] is False


@pytest.mark.asyncio
async def test_first_lesson_completed_unlocks_second(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"pp-unlock-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    l1 = await _make_lesson(db, chapter.id, 1)
    await _make_lesson(db, chapter.id, 2)
    await _make_progress(db, student.id, l1.id, "completed")

    resp = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    lessons = resp.json()["data"]["current_step"]["lessons"]
    assert lessons[0]["is_accessible"] is True
    assert lessons[1]["is_accessible"] is True


@pytest.mark.asyncio
async def test_admin_locked_lesson_never_accessible(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"pp-adminlock-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    await _make_lesson(db, chapter.id, 1, is_locked=True)

    resp = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    lesson = resp.json()["data"]["current_step"]["lessons"][0]
    assert lesson["is_accessible"] is False
    assert lesson["is_admin_locked"] is True


@pytest.mark.asyncio
async def test_step_completion_advances_current_step(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"pp-step2-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course1 = await _make_course(db)
    course2 = await _make_course(db)
    await _make_program_step(db, program.id, course1.id, 1)
    await _make_program_step(db, program.id, course2.id, 2)
    await _make_program_enrollment(db, student.id, program.id)
    # step1 course is completed
    await _make_enrollment(db, student.id, course1.id, "completed")
    await _make_enrollment(db, student.id, course2.id)

    chapter2 = await _make_chapter(db, course2.id, 1)
    await _make_lesson(db, chapter2.id, 1)

    resp = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["completed_steps"] == 1
    assert data["current_step"]["step_position"] == 2
    assert data["current_step"]["course_id"] == str(course2.id)


@pytest.mark.asyncio
async def test_all_steps_completed_current_step_is_null(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"pp-done-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id, "completed")

    resp = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["current_step"] is None
    assert data["completed_steps"] == data["total_steps"]


# ── save_progress unlock gate ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_progress_allowed_on_first_accessible_lesson(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"sg-allow-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    l1 = await _make_lesson(db, chapter.id, 1)

    resp = await client.post(
        f"/api/v1/lessons/{l1.id}/progress",
        json={"status": "in_progress", "watch_seconds": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_save_progress_blocked_on_locked_lesson(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"sg-blocked-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    await _make_lesson(db, chapter.id, 1)   # lesson 1 not completed
    l2 = await _make_lesson(db, chapter.id, 2)  # lesson 2 sequentially locked

    resp = await client.post(
        f"/api/v1/lessons/{l2.id}/progress",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "LESSON_LOCKED"


@pytest.mark.asyncio
async def test_save_progress_admin_locked_lesson_blocked(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"sg-adminlk-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    l1 = await _make_lesson(db, chapter.id, 1, is_locked=True)

    resp = await client.post(
        f"/api/v1/lessons/{l1.id}/progress",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "LESSON_LOCKED"


@pytest.mark.asyncio
async def test_save_progress_allowed_after_preceding_lesson_completed(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, token = await _make_user(db, f"sg-seq-{uuid.uuid4().hex[:6]}@example.com")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_program_step(db, program.id, course.id, 1)
    await _make_program_enrollment(db, student.id, program.id)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    l1 = await _make_lesson(db, chapter.id, 1)
    l2 = await _make_lesson(db, chapter.id, 2)
    await _make_progress(db, student.id, l1.id, "completed")

    resp = await client.post(
        f"/api/v1/lessons/{l2.id}/progress",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_save_progress_standalone_course_not_gated(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student with no ProgramEnrollment can still save progress on standalone courses."""
    student, token = await _make_user(db, f"sg-standalone-{uuid.uuid4().hex[:6]}@example.com")
    # No program enrollment — standalone course
    course = await _make_course(db)
    await _make_enrollment(db, student.id, course.id)

    chapter = await _make_chapter(db, course.id, 1)
    lesson = await _make_lesson(db, chapter.id, 1)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/progress",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
