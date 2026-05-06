"""AL-BE-10 — Seed bootstrap smoke tests.

Each test validates one aligned subsystem in isolation using shared ``client``
and ``db`` fixtures.  No dependency on the seed script itself — every test
constructs its own data.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LessonLocked, NoMarketForCountry
from app.core.security import create_access_token, hash_password
from app.db.models.batch import Batch, BatchEnrollment, BatchTransferRequest
from app.db.models.placement import PlacementAttempt, PlacementResult
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.subscription import Subscription, SubscriptionPlan
from app.db.models.user import User
from app.modules.programs.unlock import LessonInfo, StepInfo, assert_lesson_accessible, find_current_step
from app.modules.subscriptions.service import resolve_market


# ── Fixture helpers ────────────────────────────────────────────────────────────


async def _make_user(db: AsyncSession, email: str, *, role: str = "student") -> tuple[User, str]:
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
    prog = Program(
        code=f"SM{uuid.uuid4().hex[:4].upper()}",
        title="Smoke Test Program",
        is_active=True,
    )
    db.add(prog)
    await db.commit()
    await db.refresh(prog)
    return prog


# ── Test 1: Market routing ────────────────────────────────────────────────────


def test_subscription_plan_market_routing_br():
    """Brazil maps to the BR market."""
    assert resolve_market("BR") == "BR"


def test_subscription_plan_market_routing_eu():
    """Portugal (PT) maps to the EU market — not its own code."""
    assert resolve_market("PT") == "EU"


def test_subscription_plan_market_routing_ca():
    """Canada maps to the CA market."""
    assert resolve_market("CA") == "CA"


def test_subscription_plan_market_routing_unknown():
    """An unsupported country raises NoMarketForCountry."""
    with pytest.raises(NoMarketForCountry):
        resolve_market("US")


def test_subscription_plan_market_routing_none():
    """None input raises NoMarketForCountry."""
    with pytest.raises(NoMarketForCountry):
        resolve_market(None)


# ── Test 2: Program step position uniqueness ───────────────────────────────────


@pytest.mark.asyncio
async def test_program_step_order_uniqueness(db: AsyncSession):
    """Two steps at the same position in a program violate the DB constraint."""
    from app.db.models.course import Course

    prog = await _make_program(db)
    course_a = Course(
        slug=f"sm-ca-{uuid.uuid4().hex[:6]}",
        title="Course A",
        status="published",
    )
    course_b = Course(
        slug=f"sm-cb-{uuid.uuid4().hex[:6]}",
        title="Course B",
        status="published",
    )
    db.add_all([course_a, course_b])
    await db.commit()
    await db.refresh(course_a)
    await db.refresh(course_b)

    step1 = ProgramStep(program_id=prog.id, course_id=course_a.id, position=1)
    db.add(step1)
    await db.commit()

    # Inserting a second step at position 1 should violate uq_program_steps_program_position
    step_dup = ProgramStep(program_id=prog.id, course_id=course_b.id, position=1)
    db.add(step_dup)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# ── Test 3: Placement result level round-trip ─────────────────────────────────


@pytest.mark.asyncio
async def test_placement_result_level_roundtrip(db: AsyncSession, client: AsyncClient):
    """A PlacementResult written to the DB is readable via GET /users/me/placement-result."""
    now = datetime.now(UTC)
    user, token = await _make_user(db, f"smoke-placement-{uuid.uuid4().hex[:6]}@test.com")
    prog = await _make_program(db)

    attempt = PlacementAttempt(
        user_id=user.id,
        answers={"q1": "b", "q2": "a"},
        score=15,
        started_at=now - timedelta(hours=1),
        completed_at=now,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    result = PlacementResult(
        user_id=user.id,
        attempt_id=attempt.id,
        program_id=prog.id,
        level="B1",
        is_override=False,
    )
    db.add(result)
    await db.commit()

    r = await client.get(
        "/api/v1/users/me/placement-result",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["level"] == "B1"
    assert data["program_id"] == str(prog.id)


# ── Test 4: Batch capacity enforcement ────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_capacity_enforced(db: AsyncSession, client: AsyncClient):
    """Adding a member beyond capacity returns 409 BATCH_AT_CAPACITY.

    Uses capacity=1 to keep the test concise — the enforcement logic is
    identical for capacity=15 (the real launch default).
    """
    now = datetime.now(UTC)
    admin, admin_token = await _make_user(
        db, f"smoke-admin-cap-{uuid.uuid4().hex[:6]}@test.com", role="admin"
    )
    student_a, _ = await _make_user(db, f"smoke-cap-a-{uuid.uuid4().hex[:6]}@test.com")
    student_b, _ = await _make_user(db, f"smoke-cap-b-{uuid.uuid4().hex[:6]}@test.com")

    prog = await _make_program(db)

    # Enroll both students in the program
    pe_a = ProgramEnrollment(user_id=student_a.id, program_id=prog.id, status="active")
    pe_b = ProgramEnrollment(user_id=student_b.id, program_id=prog.id, status="active")
    db.add_all([pe_a, pe_b])
    await db.commit()

    # Batch with capacity=1 — enough to test the limit cleanly
    batch = Batch(
        program_id=prog.id,
        title=f"Smoke Capacity Batch {uuid.uuid4().hex[:4]}",
        status="active",
        timezone="UTC",
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=30),
        capacity=1,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    # Fill the one seat directly
    db.add(BatchEnrollment(
        batch_id=batch.id,
        user_id=student_a.id,
        program_enrollment_id=pe_a.id,
    ))
    await db.commit()

    # Try to add a second member via the API — must be rejected
    r = await client.post(
        f"/api/v1/admin/batches/{batch.id}/members",
        json={"user_id": str(student_b.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BATCH_AT_CAPACITY"


# ── Test 5: Unlock engine step gate ──────────────────────────────────────────


def test_unlock_engine_step_gate_pure():
    """Step 2 is locked until step 1 is completed — pure engine, no DB needed."""
    step1_id = uuid.uuid4()
    step2_id = uuid.uuid4()
    course1_id = uuid.uuid4()
    course2_id = uuid.uuid4()

    # Step 1 not completed → current step is step 1
    steps_in_progress = [
        StepInfo(step_id=step1_id, course_id=course1_id, position=1,
                 is_required=True, course_enrollment_status="active"),
        StepInfo(step_id=step2_id, course_id=course2_id, position=2,
                 is_required=True, course_enrollment_status=None),
    ]
    current = find_current_step(steps_in_progress)
    assert current is not None
    assert current.step_id == step1_id

    # Step 1 completed → current step advances to step 2
    steps_step1_done = [
        StepInfo(step_id=step1_id, course_id=course1_id, position=1,
                 is_required=True, course_enrollment_status="completed"),
        StepInfo(step_id=step2_id, course_id=course2_id, position=2,
                 is_required=True, course_enrollment_status="active"),
    ]
    current = find_current_step(steps_step1_done)
    assert current is not None
    assert current.step_id == step2_id


def test_unlock_engine_lesson_gate_pure():
    """Second lesson is inaccessible until the first lesson is completed."""
    lesson1_id = uuid.uuid4()
    lesson2_id = uuid.uuid4()
    chapter_id = uuid.uuid4()

    lessons_not_started = [
        LessonInfo(lesson_id=lesson1_id, chapter_id=chapter_id, chapter_title="Ch 1",
                   lesson_title="Lesson 1", position_in_course=0, is_locked=False,
                   progress_status="not_started", completed_at=None),
        LessonInfo(lesson_id=lesson2_id, chapter_id=chapter_id, chapter_title="Ch 1",
                   lesson_title="Lesson 2", position_in_course=1, is_locked=False,
                   progress_status="not_started", completed_at=None),
    ]
    # Lesson 1 is accessible (first in sequence)
    # Lesson 2 is not accessible until lesson 1 is completed
    with pytest.raises(LessonLocked):
        assert_lesson_accessible(lessons_not_started, lesson2_id)

    # After lesson 1 is completed, lesson 2 becomes accessible
    lessons_l1_done = [
        LessonInfo(lesson_id=lesson1_id, chapter_id=chapter_id, chapter_title="Ch 1",
                   lesson_title="Lesson 1", position_in_course=0, is_locked=False,
                   progress_status="completed", completed_at=datetime.now(UTC)),
        LessonInfo(lesson_id=lesson2_id, chapter_id=chapter_id, chapter_title="Ch 1",
                   lesson_title="Lesson 2", position_in_course=1, is_locked=False,
                   progress_status="not_started", completed_at=None),
    ]
    # Should not raise
    assert_lesson_accessible(lessons_l1_done, lesson2_id)


# ── Test 6: Transfer request approve moves batch enrollment ───────────────────


@pytest.mark.asyncio
async def test_transfer_request_approve_moves_enrollment(db: AsyncSession, client: AsyncClient):
    """Admin approving a transfer request moves the student from batch A to batch B."""
    now = datetime.now(UTC)
    admin, admin_token = await _make_user(
        db, f"smoke-admin-tr-{uuid.uuid4().hex[:6]}@test.com", role="admin"
    )
    student, _ = await _make_user(db, f"smoke-tr-student-{uuid.uuid4().hex[:6]}@test.com")

    prog = await _make_program(db)
    pe = ProgramEnrollment(user_id=student.id, program_id=prog.id, status="active")
    db.add(pe)
    await db.commit()
    await db.refresh(pe)

    batch_a = Batch(
        program_id=prog.id,
        title=f"Smoke TR Batch A {uuid.uuid4().hex[:4]}",
        status="active",
        timezone="UTC",
        starts_at=now - timedelta(days=7),
        ends_at=now + timedelta(days=60),
        capacity=15,
    )
    batch_b = Batch(
        program_id=prog.id,
        title=f"Smoke TR Batch B {uuid.uuid4().hex[:4]}",
        status="upcoming",
        timezone="UTC",
        starts_at=now + timedelta(days=14),
        ends_at=now + timedelta(days=104),
        capacity=15,
    )
    db.add_all([batch_a, batch_b])
    await db.commit()
    await db.refresh(batch_a)
    await db.refresh(batch_b)

    enrollment = BatchEnrollment(
        batch_id=batch_a.id,
        user_id=student.id,
        program_enrollment_id=pe.id,
    )
    db.add(enrollment)
    await db.commit()

    transfer = BatchTransferRequest(
        user_id=student.id,
        from_batch_id=batch_a.id,
        to_batch_id=batch_b.id,
        status="pending",
        reason="Schedule change.",
    )
    db.add(transfer)
    await db.commit()
    await db.refresh(transfer)

    # Admin approves
    r = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{transfer.id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "approved"

    # Student is now in batch B, not batch A
    new_enr = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.user_id == student.id,
            BatchEnrollment.batch_id == batch_b.id,
        )
    )
    assert new_enr is not None

    old_enr = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.user_id == student.id,
            BatchEnrollment.batch_id == batch_a.id,
        )
    )
    assert old_enr is None
