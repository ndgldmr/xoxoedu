"""Integration tests for AL-BE-8 — Admin Reporting and Operational APIs.

Tests cover:
- GET /admin/programs/{program_id}/students (roster, pagination, all filters)
- GET /admin/batches/{batch_id}/progress (progress, pagination, completion math)
- Regression: GET /admin/placement-results now returns meta.total + program_id filter
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.batch import Batch, BatchEnrollment
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.placement import PlacementAttempt, PlacementResult
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.quiz import Quiz, QuizSubmission
from app.db.models.subscription import Subscription
from app.db.models.user import User


# ── Fixture helpers ────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession,
    email: str,
    *,
    role: str = "student",
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=f"u_{uuid.uuid4().hex[:8]}",
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
        code=f"P{uuid.uuid4().hex[:4].upper()}",
        title="Test Program",
        is_active=True,
    )
    db.add(program)
    await db.commit()
    await db.refresh(program)
    return program


async def _make_course(db: AsyncSession) -> Course:
    course = Course(
        slug=f"course-{uuid.uuid4().hex[:8]}",
        title="Test Course",
        status="published",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_chapter(db: AsyncSession, course_id: uuid.UUID) -> Chapter:
    chapter = Chapter(course_id=course_id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def _make_lesson(db: AsyncSession, chapter_id: uuid.UUID) -> Lesson:
    lesson = Lesson(
        chapter_id=chapter_id,
        title=f"Lesson {uuid.uuid4().hex[:4]}",
        type="text",
        content={"body": "hello"},
        position=1,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_step(
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


async def _make_batch(db: AsyncSession, program_id: uuid.UUID) -> Batch:
    now = datetime.now(UTC)
    batch = Batch(
        program_id=program_id,
        title=f"Batch {uuid.uuid4().hex[:6]}",
        status="active",
        timezone="America/New_York",
        starts_at=now - timedelta(days=7),
        ends_at=now + timedelta(days=90),
        capacity=30,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def _enroll_in_program(
    db: AsyncSession,
    user: User,
    program: Program,
    *,
    status: str = "active",
) -> ProgramEnrollment:
    pe = ProgramEnrollment(
        user_id=user.id,
        program_id=program.id,
        status=status,
    )
    db.add(pe)
    await db.commit()
    await db.refresh(pe)
    return pe


async def _enroll_in_batch(
    db: AsyncSession,
    batch: Batch,
    user: User,
    pe: ProgramEnrollment,
) -> BatchEnrollment:
    be = BatchEnrollment(
        batch_id=batch.id,
        user_id=user.id,
        program_enrollment_id=pe.id,
    )
    db.add(be)
    await db.commit()
    await db.refresh(be)
    return be


async def _make_subscription(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str = "active",
) -> Subscription:
    sub = Subscription(
        user_id=user_id,
        market="BR",
        currency="BRL",
        amount_cents=1000,
        status=status,
        provider_subscription_id=f"sub_{uuid.uuid4().hex}",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def _complete_lesson(
    db: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
) -> LessonProgress:
    progress = LessonProgress(
        user_id=user_id,
        lesson_id=lesson_id,
        status="completed",
        completed_at=datetime.now(UTC),
    )
    db.add(progress)
    await db.commit()
    await db.refresh(progress)
    return progress


async def _make_quiz_submission(
    db: AsyncSession,
    user_id: uuid.UUID,
    quiz_id: uuid.UUID,
    score: int,
    max_score: int,
) -> QuizSubmission:
    sub = QuizSubmission(
        user_id=user_id,
        quiz_id=quiz_id,
        attempt_number=1,
        answers={},
        score=score,
        max_score=max_score,
        passed=score == max_score,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def _make_assignment_submission(
    db: AsyncSession,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    grade_score: float,
    *,
    published: bool = True,
) -> AssignmentSubmission:
    sub = AssignmentSubmission(
        user_id=user_id,
        assignment_id=assignment_id,
        file_key=f"uploads/{uuid.uuid4().hex}.pdf",
        file_name="submission.pdf",
        file_size=1024,
        mime_type="application/pdf",
        scan_status="clean",
        submitted_at=datetime.now(UTC),
        attempt_number=1,
        grade_score=grade_score,
        grade_published_at=datetime.now(UTC) if published else None,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


# ── Group A: GET /admin/programs/{program_id}/students ─────────────────────────

@pytest.mark.asyncio
async def test_program_students_returns_enrolled_roster(
    client: AsyncClient, db: AsyncSession
) -> None:
    """All enrolled students appear in the roster."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)

    for i in range(3):
        student, _ = await _make_user(db, f"s{i}_{uuid.uuid4().hex[:6]}@test.com")
        await _enroll_in_program(db, student, program)

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 3
    assert len(body["data"]) == 3


@pytest.mark.asyncio
async def test_program_students_pagination(
    client: AsyncClient, db: AsyncSession
) -> None:
    """skip/limit pagination returns the correct window and total."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)

    for i in range(5):
        student, _ = await _make_user(db, f"sp{i}_{uuid.uuid4().hex[:6]}@test.com")
        await _enroll_in_program(db, student, program)

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students?skip=2&limit=2",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 5
    assert len(body["data"]) == 2


@pytest.mark.asyncio
async def test_program_students_filter_by_enrollment_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    """enrollment_status filter returns only matching rows."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)

    for _ in range(2):
        s, _ = await _make_user(db, f"sa_{uuid.uuid4().hex[:6]}@test.com")
        await _enroll_in_program(db, s, program, status="active")

    s3, _ = await _make_user(db, f"ss_{uuid.uuid4().hex[:6]}@test.com")
    await _enroll_in_program(db, s3, program, status="suspended")

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students?enrollment_status=active",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert all(r["enrollment_status"] == "active" for r in body["data"])


@pytest.mark.asyncio
async def test_program_students_filter_by_batch_id(
    client: AsyncClient, db: AsyncSession
) -> None:
    """batch_id filter returns only students in that batch."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    # 2 students enrolled in batch, 1 without batch
    s1, _ = await _make_user(db, f"sb1_{uuid.uuid4().hex[:6]}@test.com")
    pe1 = await _enroll_in_program(db, s1, program)
    await _enroll_in_batch(db, batch, s1, pe1)

    s2, _ = await _make_user(db, f"sb2_{uuid.uuid4().hex[:6]}@test.com")
    pe2 = await _enroll_in_program(db, s2, program)
    await _enroll_in_batch(db, batch, s2, pe2)

    s3, _ = await _make_user(db, f"sb3_{uuid.uuid4().hex[:6]}@test.com")
    await _enroll_in_program(db, s3, program)  # no batch

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students?batch_id={batch.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert all(r["batch_id"] == str(batch.id) for r in body["data"])


@pytest.mark.asyncio
async def test_program_students_filter_by_subscription_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    """subscription_status filter returns only students with that subscription state."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)

    s1, _ = await _make_user(db, f"sub1_{uuid.uuid4().hex[:6]}@test.com")
    await _enroll_in_program(db, s1, program)
    await _make_subscription(db, s1.id, status="active")

    s2, _ = await _make_user(db, f"sub2_{uuid.uuid4().hex[:6]}@test.com")
    await _enroll_in_program(db, s2, program)
    await _make_subscription(db, s2.id, status="active")

    s3, _ = await _make_user(db, f"sub3_{uuid.uuid4().hex[:6]}@test.com")
    await _enroll_in_program(db, s3, program)
    await _make_subscription(db, s3.id, status="canceled")

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students?subscription_status=active",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert all(r["subscription_status"] == "active" for r in body["data"])


@pytest.mark.asyncio
async def test_program_students_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token is rejected with 403."""
    program = await _make_program(db)
    _, student_token = await _make_user(db, f"student_{uuid.uuid4().hex[:6]}@test.com")

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_program_students_unknown_program_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Non-existent program UUID returns 404."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")

    resp = await client.get(
        f"/api/v1/admin/programs/{uuid.uuid4()}/students",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_program_students_no_batch_shows_null_fields(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Students without a batch assignment have null batch_id and batch_title."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    student, _ = await _make_user(db, f"nobatch_{uuid.uuid4().hex[:6]}@test.com")
    await _enroll_in_program(db, student, program)

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/students",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["batch_id"] is None
    assert row["batch_title"] is None
    assert row["subscription_status"] is None


# ── Group B: GET /admin/batches/{batch_id}/progress ───────────────────────────

@pytest.mark.asyncio
async def test_batch_progress_returns_all_members(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Both students in a batch appear in the progress report."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_step(db, program.id, course.id, 1)
    batch = await _make_batch(db, program.id)

    for i in range(2):
        s, _ = await _make_user(db, f"bp{i}_{uuid.uuid4().hex[:6]}@test.com")
        pe = await _enroll_in_program(db, s, program)
        await _enroll_in_batch(db, batch, s, pe)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2


@pytest.mark.asyncio
async def test_batch_progress_pagination(
    client: AsyncClient, db: AsyncSession
) -> None:
    """skip/limit returns the correct window and meta.total."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_step(db, program.id, course.id, 1)
    batch = await _make_batch(db, program.id)

    for i in range(5):
        s, _ = await _make_user(db, f"bpp{i}_{uuid.uuid4().hex[:6]}@test.com")
        pe = await _enroll_in_program(db, s, program)
        await _enroll_in_batch(db, batch, s, pe)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress?skip=2&limit=2",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 5
    assert len(body["data"]) == 2


@pytest.mark.asyncio
async def test_batch_progress_completion_pct_accurate(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Completing 1 of 2 lessons in a course yields completion_pct == 0.5."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)
    chapter = await _make_chapter(db, course.id)
    lesson1 = await _make_lesson(db, chapter.id)
    lesson2 = Lesson(
        chapter_id=chapter.id,
        title="Lesson 2",
        type="text",
        content={"body": "world"},
        position=2,
    )
    db.add(lesson2)
    await db.commit()
    await db.refresh(lesson2)

    await _make_step(db, program.id, course.id, 1)
    batch = await _make_batch(db, program.id)
    student, _ = await _make_user(db, f"comp_{uuid.uuid4().hex[:6]}@test.com")
    pe = await _enroll_in_program(db, student, program)
    await _enroll_in_batch(db, batch, student, pe)
    await _complete_lesson(db, student.id, lesson1.id)  # 1 of 2 done

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["courses"][0]["completion_pct"] == pytest.approx(0.5)
    assert row["overall_completion_pct"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_batch_progress_zero_pct_when_no_progress(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student with no LessonProgress rows has completion_pct == 0.0."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)
    chapter = await _make_chapter(db, course.id)
    await _make_lesson(db, chapter.id)
    await _make_step(db, program.id, course.id, 1)
    batch = await _make_batch(db, program.id)
    student, _ = await _make_user(db, f"zero_{uuid.uuid4().hex[:6]}@test.com")
    pe = await _enroll_in_program(db, student, program)
    await _enroll_in_batch(db, batch, student, pe)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["courses"][0]["completion_pct"] == pytest.approx(0.0)
    assert row["overall_completion_pct"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_batch_progress_full_completion(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Completing all lessons yields completion_pct == 1.0."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_step(db, program.id, course.id, 1)
    batch = await _make_batch(db, program.id)
    student, _ = await _make_user(db, f"full_{uuid.uuid4().hex[:6]}@test.com")
    pe = await _enroll_in_program(db, student, program)
    await _enroll_in_batch(db, batch, student, pe)
    await _complete_lesson(db, student.id, lesson.id)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["courses"][0]["completion_pct"] == pytest.approx(1.0)
    assert row["overall_completion_pct"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_batch_progress_overall_pct_averages_required_steps(
    client: AsyncClient, db: AsyncSession
) -> None:
    """overall_completion_pct is the mean of required steps only."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)

    # Course 1: 1 lesson, student completes it → pct = 1.0 (required)
    c1 = await _make_course(db)
    ch1 = await _make_chapter(db, c1.id)
    l1 = await _make_lesson(db, ch1.id)
    await _make_step(db, program.id, c1.id, 1, is_required=True)

    # Course 2: 2 lessons, student completes 1 → pct = 0.5 (required)
    c2 = await _make_course(db)
    ch2 = await _make_chapter(db, c2.id)
    l2a = await _make_lesson(db, ch2.id)
    l2b = Lesson(chapter_id=ch2.id, title="L2b", type="text", content={"body": "x"}, position=2)
    db.add(l2b)
    await db.commit()
    await _make_step(db, program.id, c2.id, 2, is_required=True)

    batch = await _make_batch(db, program.id)
    student, _ = await _make_user(db, f"avg_{uuid.uuid4().hex[:6]}@test.com")
    pe = await _enroll_in_program(db, student, program)
    await _enroll_in_batch(db, batch, student, pe)
    await _complete_lesson(db, student.id, l1.id)   # course 1: 100%
    await _complete_lesson(db, student.id, l2a.id)  # course 2: 50%

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    # overall = (1.0 + 0.5) / 2 = 0.75
    assert row["overall_completion_pct"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_batch_progress_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token is rejected with 403."""
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    _, student_token = await _make_user(db, f"student_{uuid.uuid4().hex[:6]}@test.com")

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_batch_progress_unknown_batch_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Non-existent batch UUID returns 404."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")

    resp = await client.get(
        f"/api/v1/admin/batches/{uuid.uuid4()}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_progress_empty_batch(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A batch with no members returns an empty list with meta.total == 0."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)
    await _make_step(db, program.id, course.id, 1)
    batch = await _make_batch(db, program.id)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


# ── Group C: Regression — GET /admin/placement-results ────────────────────────

@pytest.mark.asyncio
async def test_placement_results_meta_has_total(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Response envelope includes meta.total, meta.page, and meta.size."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")

    resp = await client.get(
        "/api/v1/admin/placement-results?page=1&size=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert "total" in meta
    assert "page" in meta
    assert "size" in meta
    assert meta["page"] == 1
    assert meta["size"] == 10


@pytest.mark.asyncio
async def test_placement_results_program_filter(
    client: AsyncClient, db: AsyncSession
) -> None:
    """program_id filter returns only results for that program."""
    _, admin_token = await _make_user(db, f"admin_{uuid.uuid4().hex[:6]}@test.com", role="admin")

    program_a = await _make_program(db)
    program_b = await _make_program(db)

    # Create one result for program_a and one for program_b
    for program in (program_a, program_b):
        student, _ = await _make_user(db, f"pr_{uuid.uuid4().hex[:6]}@test.com")
        result_row = PlacementResult(
            user_id=student.id,
            program_id=program.id,
            level="b1_to_b2",
            is_override=True,
        )
        db.add(result_row)
    await db.commit()

    resp = await client.get(
        f"/api/v1/admin/placement-results?program_id={program_a.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 1
    assert all(r["program_id"] == str(program_a.id) for r in body["data"])
