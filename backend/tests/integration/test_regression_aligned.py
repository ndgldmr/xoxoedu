"""AL-BE-10 — Cross-feature regression tests for the aligned backend domain.

Each test exercises a realistic end-to-end journey spanning multiple subsystems
(placement → programs → batches, subscriptions → enrollment, etc.).

External calls (Stripe, email) are mocked where they would be triggered.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SubscriptionRequired
from app.core.security import create_access_token, hash_password
from app.db.models.batch import Batch, BatchEnrollment, BatchTransferRequest
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.placement import PlacementAttempt, PlacementResult
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.subscription import BillingCycle, Subscription, SubscriptionPlan
from app.db.models.user import User
from app.modules.notifications.constants import NotificationType
from app.modules.notifications.service import (
    billing_reminder_eligible,
    billing_reminder_target_date,
    build_payment_due_soon_notification,
)


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
        country="BR",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_program(db: AsyncSession, code: str | None = None) -> Program:
    prog = Program(
        code=code or f"RG{uuid.uuid4().hex[:4].upper()}",
        title="Regression Test Program",
        is_active=True,
    )
    db.add(prog)
    await db.commit()
    await db.refresh(prog)
    return prog


async def _make_course_with_lesson(db: AsyncSession, admin_id: uuid.UUID) -> tuple[Course, Lesson]:
    """Create a published course with exactly one text lesson."""
    course = Course(
        slug=f"rg-{uuid.uuid4().hex[:8]}",
        title=f"Regression Course {uuid.uuid4().hex[:4]}",
        status="published",
        created_by=admin_id,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    chapter = Chapter(course_id=course.id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)

    lesson = Lesson(
        chapter_id=chapter.id,
        title="Lesson 1",
        type="text",
        position=1,
        is_free_preview=True,
        content={"body": "<p>Regression test lesson content.</p>"},
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return course, lesson


async def _make_batch(
    db: AsyncSession,
    program_id: uuid.UUID,
    *,
    status: str = "active",
) -> Batch:
    now = datetime.now(UTC)
    batch = Batch(
        program_id=program_id,
        title=f"Regression Batch {uuid.uuid4().hex[:4]}",
        status=status,
        timezone="UTC",
        starts_at=now - timedelta(days=7) if status == "active" else now + timedelta(days=7),
        ends_at=now + timedelta(days=60),
        capacity=15,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


# ── Journey 1: Student onboarding → placement → program → batch ───────────────


@pytest.mark.asyncio
async def test_student_onboarding_to_batch(db: AsyncSession, client: AsyncClient):
    """Admin places student: placement result → program enrollment → batch assignment.

    Verifies the full admin-side onboarding flow and that student endpoints
    reflect the new state.
    """
    admin, admin_token = await _make_user(
        db, f"rg-admin-ob-{uuid.uuid4().hex[:6]}@test.com", role="admin"
    )
    student, student_token = await _make_user(
        db, f"rg-student-ob-{uuid.uuid4().hex[:6]}@test.com"
    )

    prog = await _make_program(db)
    course, _ = await _make_course_with_lesson(db, admin.id)

    db.add(ProgramStep(program_id=prog.id, course_id=course.id, position=1, is_required=True))
    await db.commit()

    # Step 1: Placement attempt + result
    now = datetime.now(UTC)
    attempt = PlacementAttempt(
        user_id=student.id,
        answers={"q1": "b", "q2": "a"},
        score=15,
        started_at=now - timedelta(hours=1),
        completed_at=now,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    result = PlacementResult(
        user_id=student.id,
        attempt_id=attempt.id,
        program_id=prog.id,
        level="B1",
        is_override=False,
    )
    db.add(result)
    await db.commit()

    # Verify placement result via student endpoint
    r = await client.get(
        "/api/v1/users/me/placement-result",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["level"] == "B1"

    # Step 2: Admin creates program enrollment
    r = await client.post(
        f"/api/v1/admin/users/{student.id}/program-enrollments",
        json={"program_id": str(prog.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201
    enrollment_id = r.json()["data"]["id"]

    # Student sees their program enrollment
    r = await client.get(
        "/api/v1/users/me/program-enrollment",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["program_id"] == str(prog.id)
    assert r.json()["data"]["status"] == "active"

    # Step 3: Admin creates a batch and adds the student
    batch = await _make_batch(db, prog.id)
    r = await client.post(
        f"/api/v1/admin/batches/{batch.id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201

    # Student can retrieve their batch
    r = await client.get(
        "/api/v1/users/me/batch",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["batch"]["id"] == str(batch.id)


# ── Journey 2: Subscription gating ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscription_gates_access(db: AsyncSession):
    """_active_subscription_guard raises SubscriptionRequired without an active sub.

    Tests the dependency function directly since no routes currently use it.
    This documents the expected behavior when it is wired to content routes.
    """
    from app.dependencies import _active_subscription_guard

    user, _ = await _make_user(
        db, f"rg-sub-gate-{uuid.uuid4().hex[:6]}@test.com"
    )

    # No subscription → should raise
    with pytest.raises(SubscriptionRequired):
        await _active_subscription_guard(current_user=user, db=db)

    # Create an active subscription
    plan = SubscriptionPlan(
        name="Gating Test Plan",
        market="BR",
        currency="BRL",
        amount_cents=2990,
        interval="month",
        is_active=True,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        market="BR",
        currency="BRL",
        amount_cents=2990,
        status="active",
        provider_subscription_id=f"sub_test_gate_{uuid.uuid4().hex[:8]}",
    )
    db.add(sub)
    await db.commit()

    # Active subscription → guard returns the user
    returned_user = await _active_subscription_guard(current_user=user, db=db)
    assert returned_user.id == user.id


# ── Journey 3: Full batch transfer workflow ────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_transfer_full_flow(db: AsyncSession, client: AsyncClient):
    """Student requests transfer → admin approves → student is in new batch.

    Verifies the complete transfer state machine including enrollment migration.
    """
    now = datetime.now(UTC)
    admin, admin_token = await _make_user(
        db, f"rg-admin-tr-{uuid.uuid4().hex[:6]}@test.com", role="admin"
    )
    student, student_token = await _make_user(
        db, f"rg-student-tr-{uuid.uuid4().hex[:6]}@test.com"
    )

    prog = await _make_program(db)
    pe = ProgramEnrollment(user_id=student.id, program_id=prog.id, status="active")
    db.add(pe)
    await db.commit()
    await db.refresh(pe)

    batch_a = await _make_batch(db, prog.id, status="active")
    batch_b = await _make_batch(db, prog.id, status="upcoming")

    # Enroll student in batch A
    db.add(BatchEnrollment(
        batch_id=batch_a.id,
        user_id=student.id,
        program_enrollment_id=pe.id,
    ))
    await db.commit()

    # Student requests transfer to batch B
    r = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": str(batch_b.id), "reason": "Schedule conflict."},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 201
    transfer_id = r.json()["data"]["id"]
    assert r.json()["data"]["status"] == "pending"

    # Admin approves the transfer
    r = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{transfer_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "approved"

    # Student's enrollment moved to batch B
    in_b = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.user_id == student.id,
            BatchEnrollment.batch_id == batch_b.id,
        )
    )
    assert in_b is not None

    in_a = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.user_id == student.id,
            BatchEnrollment.batch_id == batch_a.id,
        )
    )
    assert in_a is None

    # Transfer request is terminal (approved)
    r = await client.get(
        "/api/v1/users/me/batch-transfer-requests",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 200
    requests = r.json()["data"]
    assert any(req["status"] == "approved" for req in requests)


# ── Journey 4: Program progression unlocks next step ──────────────────────────


@pytest.mark.asyncio
async def test_program_progression_unlocks_next_step(db: AsyncSession, client: AsyncClient):
    """Completing all lessons in step 1 advances the student to step 2.

    Specifically:
    - Enrollment.status transitions to "completed" after last lesson
    - GET /users/me/program-progress reports step 2 as the current step
    """
    admin, _ = await _make_user(
        db, f"rg-admin-prog-{uuid.uuid4().hex[:6]}@test.com", role="admin"
    )
    student, student_token = await _make_user(
        db, f"rg-student-prog-{uuid.uuid4().hex[:6]}@test.com"
    )

    prog = await _make_program(db)
    course1, lesson1 = await _make_course_with_lesson(db, admin.id)
    course2, lesson2 = await _make_course_with_lesson(db, admin.id)

    db.add_all([
        ProgramStep(program_id=prog.id, course_id=course1.id, position=1, is_required=True),
        ProgramStep(program_id=prog.id, course_id=course2.id, position=2, is_required=True),
    ])
    await db.commit()

    # Enroll student in program and in step 1 course
    pe = ProgramEnrollment(user_id=student.id, program_id=prog.id, status="active")
    db.add(pe)
    await db.commit()

    enr = Enrollment(user_id=student.id, course_id=course1.id, status="active")
    db.add(enr)
    await db.commit()

    # Complete lesson 1 via API (lesson 1 is always accessible as first in sequence)
    r = await client.post(
        f"/api/v1/lessons/{lesson1.id}/progress",
        json={"status": "completed"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "completed"

    # Enrollment should now be "completed" (only 1 lesson in course)
    await db.refresh(enr)
    assert enr.status == "completed"

    # GET /users/me/program-progress should show step 2 as current
    r = await client.get(
        "/api/v1/users/me/program-progress",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert r.status_code == 200
    progress = r.json()["data"]
    assert progress["completed_steps"] == 1
    assert progress["total_steps"] == 2
    assert progress["current_step"]["step_position"] == 2
    assert progress["current_step"]["course_id"] == str(course2.id)


# ── Journey 5: Admin reporting surfaces ───────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_reporting_surfaces(db: AsyncSession, client: AsyncClient):
    """Admin program roster, batch progress, and placement results endpoints return correct data.

    Creates a minimal but realistic dataset:
    - 1 program with 1 step (1 course, 2 lessons)
    - 1 batch with 2 enrolled students
    - Student A: completed 2/2 lessons
    - Student B: completed 1/2 lessons
    """
    admin, admin_token = await _make_user(
        db, f"rg-admin-report-{uuid.uuid4().hex[:6]}@test.com", role="admin"
    )
    student_a, _ = await _make_user(db, f"rg-rpt-a-{uuid.uuid4().hex[:6]}@test.com")
    student_b, _ = await _make_user(db, f"rg-rpt-b-{uuid.uuid4().hex[:6]}@test.com")

    prog = await _make_program(db)

    # Course with 2 lessons
    course = Course(
        slug=f"rg-rpt-{uuid.uuid4().hex[:8]}",
        title="Reporting Test Course",
        status="published",
        created_by=admin.id,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    chapter = Chapter(course_id=course.id, title="Ch 1", position=1)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)

    lesson_a = Lesson(chapter_id=chapter.id, title="Lesson A", type="text", position=1,
                      content={"body": "<p>A</p>"})
    lesson_b = Lesson(chapter_id=chapter.id, title="Lesson B", type="text", position=2,
                      content={"body": "<p>B</p>"})
    db.add_all([lesson_a, lesson_b])
    await db.commit()
    await db.refresh(lesson_a)
    await db.refresh(lesson_b)

    db.add(ProgramStep(program_id=prog.id, course_id=course.id, position=1, is_required=True))
    await db.commit()

    pe_a = ProgramEnrollment(user_id=student_a.id, program_id=prog.id, status="active")
    pe_b = ProgramEnrollment(user_id=student_b.id, program_id=prog.id, status="active")
    db.add_all([pe_a, pe_b])
    await db.commit()
    await db.refresh(pe_a)
    await db.refresh(pe_b)

    batch = await _make_batch(db, prog.id)
    db.add_all([
        BatchEnrollment(batch_id=batch.id, user_id=student_a.id, program_enrollment_id=pe_a.id),
        BatchEnrollment(batch_id=batch.id, user_id=student_b.id, program_enrollment_id=pe_b.id),
    ])
    await db.commit()

    now = datetime.now(UTC)
    # Student A: 2/2 lessons completed
    db.add_all([
        LessonProgress(user_id=student_a.id, lesson_id=lesson_a.id, status="completed", completed_at=now),
        LessonProgress(user_id=student_a.id, lesson_id=lesson_b.id, status="completed", completed_at=now),
    ])
    # Student B: 1/2 lessons completed
    db.add(LessonProgress(user_id=student_b.id, lesson_id=lesson_a.id, status="completed", completed_at=now))
    await db.commit()

    # GET /admin/programs/{id}/students — both students should appear
    r = await client.get(
        f"/api/v1/admin/programs/{prog.id}/students",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["meta"]["total"] == 2
    student_ids = {s["user_id"] for s in payload["data"]}
    assert str(student_a.id) in student_ids
    assert str(student_b.id) in student_ids

    # GET /admin/batches/{id}/progress — completion rates differ
    r = await client.get(
        f"/api/v1/admin/batches/{batch.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["meta"]["total"] == 2
    by_user = {row["user_id"]: row for row in payload["data"]}
    assert by_user[str(student_a.id)]["overall_completion_pct"] == 1.0
    assert by_user[str(student_b.id)]["overall_completion_pct"] == 0.5

    # GET /admin/placement-results — no results for this program (none seeded here)
    # Just verify the endpoint returns 200 with correct meta structure
    r = await client.get(
        f"/api/v1/admin/placement-results?program_id={prog.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert "total" in r.json()["meta"]


# ── Journey 6: Billing notification reminder dispatch ─────────────────────────


def test_billing_reminder_eligible_logic():
    """billing_reminder_eligible gate: pending + unsent + right date → True."""
    today = date(2026, 5, 1)
    target = billing_reminder_target_date(today)  # today + 3 days = 2026-05-04

    # Eligible: pending, no reminder sent, active subscription, due on target date
    assert billing_reminder_eligible(
        cycle_status="pending",
        due_date=target,
        reminder_sent_at=None,
        subscription_status="active",
        today=today,
    ) is True

    # Not eligible: already paid
    assert billing_reminder_eligible(
        cycle_status="paid",
        due_date=target,
        reminder_sent_at=None,
        subscription_status="active",
        today=today,
    ) is False

    # Not eligible: reminder already sent
    assert billing_reminder_eligible(
        cycle_status="pending",
        due_date=target,
        reminder_sent_at=datetime(2026, 4, 30, tzinfo=UTC),
        subscription_status="active",
        today=today,
    ) is False

    # Not eligible: canceled subscription
    assert billing_reminder_eligible(
        cycle_status="pending",
        due_date=target,
        reminder_sent_at=None,
        subscription_status="canceled",
        today=today,
    ) is False

    # Not eligible: wrong due date (too early)
    assert billing_reminder_eligible(
        cycle_status="pending",
        due_date=date(2026, 5, 10),
        reminder_sent_at=None,
        subscription_status="active",
        today=today,
    ) is False


def test_build_payment_due_soon_notification_structure():
    """build_payment_due_soon_notification returns a Notification with correct fields."""
    user_id = uuid.uuid4()
    subscription_id = uuid.uuid4()
    billing_cycle_id = uuid.uuid4()
    due_date = date(2026, 5, 4)

    notification = build_payment_due_soon_notification(
        recipient_id=user_id,
        subscription_id=subscription_id,
        billing_cycle_id=billing_cycle_id,
        due_date=due_date,
        amount_cents=2990,
        currency="BRL",
        provider_invoice_id=None,
    )

    assert notification.recipient_id == user_id
    assert notification.type == NotificationType.PAYMENT_DUE_SOON
    assert "BRL" in notification.body
    assert "29.90" in notification.body
    assert str(subscription_id) in notification.event_metadata["subscription_id"]
    assert notification.event_metadata["amount_cents"] == 2990
    assert notification.event_metadata["currency"] == "BRL"
    assert notification.target_url == "/home/account"


@pytest.mark.asyncio
async def test_billing_reminder_creates_notification_in_db(db: AsyncSession):
    """A past_due billing cycle with due_date=target generates a Notification row."""
    from app.db.models.notification import Notification

    today = date.today()
    target_due = billing_reminder_target_date(today)

    user, _ = await _make_user(
        db, f"rg-billing-{uuid.uuid4().hex[:6]}@test.com"
    )
    plan = SubscriptionPlan(
        name="Billing Reminder Test Plan",
        market="BR",
        currency="BRL",
        amount_cents=2990,
        interval="month",
        is_active=True,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        market="BR",
        currency="BRL",
        amount_cents=2990,
        status="active",
        provider_subscription_id=f"sub_reminder_{uuid.uuid4().hex[:8]}",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    cycle = BillingCycle(
        subscription_id=sub.id,
        due_date=target_due,
        amount_cents=2990,
        currency="BRL",
        status="pending",
        reminder_sent_at=None,
    )
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)

    # Verify eligibility
    assert billing_reminder_eligible(
        cycle_status=cycle.status,
        due_date=cycle.due_date,
        reminder_sent_at=cycle.reminder_sent_at,
        subscription_status=sub.status,
        today=today,
    ) is True

    # Build and persist the notification directly (mirrors send_billing_cycle_reminder logic)
    notification = build_payment_due_soon_notification(
        recipient_id=sub.user_id,
        subscription_id=sub.id,
        billing_cycle_id=cycle.id,
        due_date=cycle.due_date,
        amount_cents=cycle.amount_cents,
        currency=cycle.currency,
        provider_invoice_id=cycle.provider_invoice_id,
    )
    db.add(notification)
    cycle.reminder_sent_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(notification)

    # Notification was written to the database
    stored = await db.scalar(
        select(Notification).where(Notification.recipient_id == user.id)
    )
    assert stored is not None
    assert stored.type == NotificationType.PAYMENT_DUE_SOON
    assert stored.event_metadata["amount_cents"] == 2990

    # Cycle.reminder_sent_at is now set — re-running would not re-notify
    await db.refresh(cycle)
    assert cycle.reminder_sent_at is not None
    assert billing_reminder_eligible(
        cycle_status=cycle.status,
        due_date=cycle.due_date,
        reminder_sent_at=cycle.reminder_sent_at,
        subscription_status=sub.status,
        today=today,
    ) is False
