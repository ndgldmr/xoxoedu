"""Integration tests for AL-BE-1 — batch CRUD and batch enrollment (program-scoped)."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.batch import BatchEnrollment, BatchTransferRequest
from app.db.models.certificate import Certificate
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.program import Program, ProgramEnrollment
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
        code=f"PT{uuid.uuid4().hex[:4].upper()}",
        title="Pronunciation Training",
        is_active=True,
    )
    db.add(program)
    await db.commit()
    await db.refresh(program)
    return program


async def _enroll_in_program(
    db: AsyncSession, user: User, program: Program
) -> ProgramEnrollment:
    pe = ProgramEnrollment(
        user_id=user.id,
        program_id=program.id,
        status="active",
    )
    db.add(pe)
    await db.commit()
    await db.refresh(pe)
    return pe


def _batch_payload(program_id: uuid.UUID, **overrides: object) -> dict:
    base = {
        "program_id": str(program_id),
        "title": "Spring 2026 Cohort",
        "timezone": "America/New_York",
        "starts_at": "2026-01-15T00:00:00Z",
        "ends_at": "2026-04-15T00:00:00Z",
    }
    base.update(overrides)
    return base


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def _seed_course_progress_state(db: AsyncSession, student: User) -> None:
    course = Course(
        slug=f"course-{uuid.uuid4().hex[:8]}",
        title="Progress Safety Course",
        status="published",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
    )
    db.add(course)
    await db.flush()

    chapter = Chapter(course_id=course.id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.flush()

    lesson = Lesson(
        chapter_id=chapter.id,
        title="Lesson 1",
        type="text",
        content={"body": "Hello"},
        position=1,
    )
    db.add(lesson)
    await db.flush()

    db.add(Enrollment(user_id=student.id, course_id=course.id, status="active"))
    db.add(
        LessonProgress(
            user_id=student.id,
            lesson_id=lesson.id,
            status="in_progress",
            watch_seconds=42,
        )
    )
    await db.commit()


async def _seed_certificate_for_student(db: AsyncSession, student: User) -> Certificate:
    enrollment = await db.scalar(
        select(Enrollment).where(Enrollment.user_id == student.id).limit(1)
    )
    assert enrollment is not None

    certificate = Certificate(
        user_id=student.id,
        course_id=enrollment.course_id,
        verification_token=secrets.token_urlsafe(16),
        pdf_url="https://example.com/certificate.pdf",
    )
    db.add(certificate)
    await db.commit()
    await db.refresh(certificate)
    return certificate


# ── Admin — batch CRUD ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_creates_batch(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_create@example.com", role="admin")
    program = await _make_program(db)

    resp = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Spring 2026 Cohort"
    assert data["status"] == "upcoming"
    assert data["timezone"] == "America/New_York"
    assert data["program_id"] == str(program.id)
    assert data["capacity"] == 15


@pytest.mark.asyncio
async def test_student_cannot_create_batch(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, "admin_for_student_test@example.com", role="admin")
    student, token = await _make_user(db, "student_create@example.com")
    program = await _make_program(db)

    resp = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_lists_program_batches(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_list@example.com", role="admin")
    program = await _make_program(db)

    for i in range(3):
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title=f"Cohort {i}"),
            headers={"Authorization": f"Bearer {token}"},
        )

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/batches",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 3


@pytest.mark.asyncio
async def test_admin_gets_batch_by_id(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_get@example.com", role="admin")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/admin/batches/{batch_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == batch_id


@pytest.mark.asyncio
async def test_admin_updates_batch_title(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_update@example.com", role="admin")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/admin/batches/{batch_id}",
        json={"title": "Renamed Cohort"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Renamed Cohort"


@pytest.mark.asyncio
async def test_admin_transitions_batch_status(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_status@example.com", role="admin")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    # upcoming → active
    resp = await client.patch(
        f"/api/v1/admin/batches/{batch_id}",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"

    # active → archived
    resp = await client.patch(
        f"/api/v1/admin/batches/{batch_id}",
        json={"status": "archived"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "archived"


@pytest.mark.asyncio
async def test_invalid_status_transition_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_bad_trans@example.com", role="admin")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    # upcoming → archived → active (not allowed)
    await client.patch(
        f"/api/v1/admin/batches/{batch_id}",
        json={"status": "archived"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.patch(
        f"/api/v1/admin/batches/{batch_id}",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_ARCHIVED"


# ── Admin — batch membership ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_adds_student_to_batch(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_add@example.com", role="admin")
    student, _ = await _make_user(db, "student_add@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["user"]["id"] == str(student.id)
    assert data["batch_id"] == batch_id


@pytest.mark.asyncio
async def test_add_member_without_program_enrollment_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Adding a student with no active program enrollment must be rejected."""
    admin, token = await _make_user(db, "admin_noenroll@example.com", role="admin")
    student, _ = await _make_user(db, "student_noenroll@example.com")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROGRAM_ENROLLMENT_REQUIRED"


@pytest.mark.asyncio
async def test_adding_student_twice_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_dup@example.com", role="admin")
    student, _ = await _make_user(db, "student_dup@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_IN_BATCH"


@pytest.mark.asyncio
async def test_archived_batch_rejects_new_member(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_arch_mem@example.com", role="admin")
    student, _ = await _make_user(db, "student_arch_mem@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    await client.patch(
        f"/api/v1/admin/batches/{batch_id}",
        json={"status": "archived"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_ARCHIVED"


@pytest.mark.asyncio
async def test_student_cannot_be_in_two_active_batches_for_same_program(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_two_batch@example.com", role="admin")
    student, _ = await _make_user(db, "student_two_batch@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    # Create two active batches for the same program
    b1 = (await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id, title="Batch A"),
        headers={"Authorization": f"Bearer {token}"},
    )).json()["data"]["id"]

    b2 = (await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id, title="Batch B"),
        headers={"Authorization": f"Bearer {token}"},
    )).json()["data"]["id"]

    for batch_id in (b1, b2):
        await client.patch(
            f"/api/v1/admin/batches/{batch_id}",
            json={"status": "active"},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Add student to the first batch — should succeed
    resp1 = await client.post(
        f"/api/v1/admin/batches/{b1}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 201

    # Add the same student to the second active batch — should fail
    resp2 = await client.post(
        f"/api/v1/admin/batches/{b2}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "STUDENT_ALREADY_IN_ACTIVE_BATCH"


@pytest.mark.asyncio
async def test_capacity_enforcement(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_cap@example.com", role="admin")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id, capacity=1),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    student1, _ = await _make_user(db, "student_cap1@example.com")
    student2, _ = await _make_user(db, "student_cap2@example.com")
    await _enroll_in_program(db, student1, program)
    await _enroll_in_program(db, student2, program)

    resp1 = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student1.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student2.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "BATCH_AT_CAPACITY"


@pytest.mark.asyncio
async def test_admin_removes_student_from_batch(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_remove@example.com", role="admin")
    student, _ = await _make_user(db, "student_remove@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.delete(
        f"/api/v1/admin/batches/{batch_id}/members/{student.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["removed"] is True


@pytest.mark.asyncio
async def test_admin_lists_batch_members(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_list_mem@example.com", role="admin")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {token}"},
    )
    batch_id = create.json()["data"]["id"]

    for i in range(3):
        s, _ = await _make_user(db, f"student_list_mem_{i}@example.com")
        await _enroll_in_program(db, s, program)
        await client.post(
            f"/api/v1/admin/batches/{batch_id}/members",
            json={"user_id": str(s.id)},
            headers={"Authorization": f"Bearer {token}"},
        )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch_id}/members",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 3


# ── Student endpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_student_lists_own_batch_memberships(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_me_batch@example.com", role="admin")
    student, student_token = await _make_user(db, "student_me_batch@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    batch_id = create.json()["data"]["id"]

    await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(student.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    resp = await client.get(
        "/api/v1/users/me/batches",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["batch"]["id"] == batch_id


@pytest.mark.asyncio
async def test_student_lists_available_batches_for_active_program_only(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_available@example.com", role="admin")
    student, student_token = await _make_user(db, "student_available@example.com")
    filler, _ = await _make_user(db, "student_available_filler@example.com")
    program = await _make_program(db)
    other_program = await _make_program(db)
    await _enroll_in_program(db, student, program)
    await _enroll_in_program(db, filler, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }

    upcoming = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Eligible Upcoming", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    active = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Eligible Active", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    await client.patch(
        f"/api/v1/admin/batches/{active}",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    other_program_batch = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(other_program.id, title="Other Program", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    archived = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Archived Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    await client.patch(
        f"/api/v1/admin/batches/{archived}",
        json={"status": "archived"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    future_open = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(
                program.id,
                title="Opens Later",
                enrollment_opens_at=_iso(now + timedelta(hours=1)),
                enrollment_closes_at=_iso(now + timedelta(days=2)),
            ),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    closed = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(
                program.id,
                title="Closed Cohort",
                enrollment_opens_at=_iso(now - timedelta(days=2)),
                enrollment_closes_at=_iso(now - timedelta(hours=1)),
            ),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    full = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Full Cohort", capacity=1, **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    add_full = await client.post(
        f"/api/v1/admin/batches/{full}/members",
        json={"user_id": str(filler.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert add_full.status_code == 201

    resp = await client.get(
        "/api/v1/users/me/batches/available",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200

    items = resp.json()["data"]
    returned_ids = {item["id"] for item in items}
    assert returned_ids == {upcoming, active}
    assert all(item["remaining_seats"] == 15 for item in items)
    assert other_program_batch not in returned_ids
    assert archived not in returned_ids
    assert future_open not in returned_ids
    assert closed not in returned_ids
    assert full not in returned_ids


@pytest.mark.asyncio
async def test_student_current_batch_endpoint_returns_null_before_selection(
    client: AsyncClient, db: AsyncSession
) -> None:
    student, student_token = await _make_user(db, "student_current_none@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    resp = await client.get(
        "/api/v1/users/me/batch",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] is None


@pytest.mark.asyncio
async def test_student_selects_eligible_batch_and_can_fetch_current_batch(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_select_ok@example.com", role="admin")
    student, student_token = await _make_user(db, "student_select_ok@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(
            program.id,
            title="Selectable Cohort",
            enrollment_opens_at=_iso(now - timedelta(days=1)),
            enrollment_closes_at=_iso(now + timedelta(days=1)),
        ),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    batch_id = create.json()["data"]["id"]

    select_resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert select_resp.status_code == 201
    assert select_resp.json()["data"]["batch"]["id"] == batch_id

    available_resp = await client.get(
        "/api/v1/users/me/batches/available",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert available_resp.status_code == 200
    assert available_resp.json()["data"] == []

    current_resp = await client.get(
        "/api/v1/users/me/batch",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert current_resp.status_code == 200
    assert current_resp.json()["data"]["batch"]["id"] == batch_id


@pytest.mark.asyncio
async def test_student_selection_rejects_cross_program_batch(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_cross_program@example.com", role="admin")
    student, student_token = await _make_user(db, "student_cross_program@example.com")
    program = await _make_program(db)
    other_program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(
            other_program.id,
            title="Wrong Program Cohort",
            enrollment_opens_at=_iso(now - timedelta(days=1)),
            enrollment_closes_at=_iso(now + timedelta(days=1)),
        ),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    batch_id = create.json()["data"]["id"]

    resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_PROGRAM_MISMATCH"


@pytest.mark.asyncio
async def test_student_selection_rejects_over_capacity(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_select_capacity@example.com", role="admin")
    student, student_token = await _make_user(db, "student_select_capacity@example.com")
    filler, _ = await _make_user(db, "student_select_capacity_filler@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)
    await _enroll_in_program(db, filler, program)

    now = datetime.now(UTC)
    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(
            program.id,
            title="Capacity One",
            capacity=1,
            enrollment_opens_at=_iso(now - timedelta(days=1)),
            enrollment_closes_at=_iso(now + timedelta(days=1)),
        ),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    batch_id = create.json()["data"]["id"]

    fill_resp = await client.post(
        f"/api/v1/admin/batches/{batch_id}/members",
        json={"user_id": str(filler.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fill_resp.status_code == 201

    resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_AT_CAPACITY"


@pytest.mark.asyncio
async def test_student_selection_rejects_second_batch_choice_in_same_program(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_second_pick@example.com", role="admin")
    student, student_token = await _make_user(db, "student_second_pick@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    batch_ids: list[str] = []
    for title in ("First Cohort", "Second Cohort"):
        create = await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(
                program.id,
                title=title,
                enrollment_opens_at=_iso(now - timedelta(days=1)),
                enrollment_closes_at=_iso(now + timedelta(days=1)),
            ),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        batch_ids.append(create.json()["data"]["id"])

    first_resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": batch_ids[0]},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert first_resp.status_code == 201

    second_resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": batch_ids[1]},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert second_resp.status_code == 409
    assert second_resp.json()["error"]["code"] == "STUDENT_ALREADY_IN_PROGRAM_BATCH"


@pytest.mark.asyncio
async def test_student_selection_does_not_mutate_progress_state(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_progress_safe@example.com", role="admin")
    student, student_token = await _make_user(db, "student_progress_safe@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)
    await _seed_course_progress_state(db, student)

    now = datetime.now(UTC)
    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(
            program.id,
            title="Progress Safe Cohort",
            enrollment_opens_at=_iso(now - timedelta(days=1)),
            enrollment_closes_at=_iso(now + timedelta(days=1)),
        ),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    batch_id = create.json()["data"]["id"]

    enrollment_count_before = await db.scalar(
        select(func.count()).where(Enrollment.user_id == student.id)
    )
    progress_count_before = await db.scalar(
        select(func.count()).where(LessonProgress.user_id == student.id)
    )

    resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 201

    enrollment_count_after = await db.scalar(
        select(func.count()).where(Enrollment.user_id == student.id)
    )
    progress_count_after = await db.scalar(
        select(func.count()).where(LessonProgress.user_id == student.id)
    )
    batch_count = await db.scalar(
        select(func.count()).where(BatchEnrollment.user_id == student.id)
    )

    assert enrollment_count_after == enrollment_count_before
    assert progress_count_after == progress_count_before
    assert batch_count == 1


@pytest.mark.asyncio
async def test_student_creates_and_lists_batch_transfer_requests(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_create@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_create@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Target Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    select_resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert select_resp.status_code == 201

    create_resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id, "reason": "Need the later time"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert create_resp.status_code == 201
    data = create_resp.json()["data"]
    assert data["status"] == "pending"
    assert data["reason"] == "Need the later time"
    assert data["from_batch"]["id"] == source_batch_id
    assert data["to_batch"]["id"] == target_batch_id

    list_resp = await client.get(
        "/api/v1/users/me/batch-transfer-requests",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == data["id"]
    assert items[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_transfer_request_requires_current_batch_membership(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_nocurrent@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_nocurrent@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(
                program.id,
                title="Target Cohort",
                enrollment_opens_at=_iso(now - timedelta(days=1)),
                enrollment_closes_at=_iso(now + timedelta(days=1)),
            ),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_TRANSFER_CURRENT_BATCH_REQUIRED"


@pytest.mark.asyncio
async def test_transfer_request_rejects_cross_program_target(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_cross@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_cross@example.com")
    program = await _make_program(db)
    other_program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(other_program.id, title="Other Program Target", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_TRANSFER_PROGRAM_MISMATCH"


@pytest.mark.asyncio
async def test_transfer_request_rejects_full_target_batch(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_full@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_full@example.com")
    filler, _ = await _make_user(db, "student_transfer_full_filler@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)
    await _enroll_in_program(db, filler, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Target Cohort", capacity=1, **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    fill_resp = await client.post(
        f"/api/v1/admin/batches/{target_batch_id}/members",
        json={"user_id": str(filler.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fill_resp.status_code == 201

    resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_AT_CAPACITY"


@pytest.mark.asyncio
async def test_admin_lists_transfer_requests_and_filters_by_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_queue@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_queue@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Target Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    create_resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id, "reason": "Need to switch"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    request_id = create_resp.json()["data"]["id"]

    pending_resp = await client.get(
        "/api/v1/admin/batch-transfer-requests?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert pending_resp.status_code == 200
    pending_data = pending_resp.json()["data"]
    assert pending_resp.json()["meta"]["total"] >= 1
    assert any(item["id"] == request_id for item in pending_data)

    deny_resp = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{request_id}/deny",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deny_resp.status_code == 200
    assert deny_resp.json()["data"]["status"] == "denied"

    denied_resp = await client.get(
        "/api/v1/admin/batch-transfer-requests?status=denied",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert denied_resp.status_code == 200
    denied_data = denied_resp.json()["data"]
    assert denied_resp.json()["meta"]["total"] >= 1
    assert any(item["id"] == request_id for item in denied_data)


@pytest.mark.asyncio
async def test_admin_approves_transfer_and_preserves_academic_state(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_approve@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_approve@example.com")
    program = await _make_program(db)
    program_enrollment = await _enroll_in_program(db, student, program)
    await _seed_course_progress_state(db, student)
    certificate = await _seed_certificate_for_student(db, student)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Target Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]

    select_resp = await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert select_resp.status_code == 201

    create_resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id, "reason": "Need a new schedule"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    request_id = create_resp.json()["data"]["id"]

    enrollment_rows_before = [
        (row.course_id, row.status, row.completed_at)
        for row in (
            await db.scalars(
                select(Enrollment)
                .where(Enrollment.user_id == student.id)
                .order_by(Enrollment.course_id.asc())
            )
        ).all()
    ]
    progress_rows_before = [
        (row.lesson_id, row.status, row.watch_seconds, row.completed_at)
        for row in (
            await db.scalars(
                select(LessonProgress)
                .where(LessonProgress.user_id == student.id)
                .order_by(LessonProgress.lesson_id.asc())
            )
        ).all()
    ]
    certificate_rows_before = [
        (row.course_id, row.verification_token, row.pdf_url)
        for row in (
            await db.scalars(
                select(Certificate)
                .where(Certificate.user_id == student.id)
                .order_by(Certificate.course_id.asc())
            )
        ).all()
    ]

    approve_resp = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{request_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["data"]["status"] == "approved"
    assert approve_resp.json()["data"]["to_batch"]["id"] == target_batch_id

    current_batch_resp = await client.get(
        "/api/v1/users/me/batch",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert current_batch_resp.status_code == 200
    assert current_batch_resp.json()["data"]["batch"]["id"] == target_batch_id

    memberships = (
        await db.scalars(
            select(BatchEnrollment).where(BatchEnrollment.user_id == student.id)
        )
    ).all()
    assert len(memberships) == 1
    assert memberships[0].batch_id == uuid.UUID(target_batch_id)
    assert memberships[0].program_enrollment_id == program_enrollment.id

    enrollment_rows_after = [
        (row.course_id, row.status, row.completed_at)
        for row in (
            await db.scalars(
                select(Enrollment)
                .where(Enrollment.user_id == student.id)
                .order_by(Enrollment.course_id.asc())
            )
        ).all()
    ]
    progress_rows_after = [
        (row.lesson_id, row.status, row.watch_seconds, row.completed_at)
        for row in (
            await db.scalars(
                select(LessonProgress)
                .where(LessonProgress.user_id == student.id)
                .order_by(LessonProgress.lesson_id.asc())
            )
        ).all()
    ]
    certificate_rows_after = [
        (row.course_id, row.verification_token, row.pdf_url)
        for row in (
            await db.scalars(
                select(Certificate)
                .where(Certificate.user_id == student.id)
                .order_by(Certificate.course_id.asc())
            )
        ).all()
    ]
    transfer_request = await db.get(BatchTransferRequest, uuid.UUID(request_id))

    assert enrollment_rows_after == enrollment_rows_before
    assert progress_rows_after == progress_rows_before
    assert certificate_rows_after == certificate_rows_before
    assert certificate_rows_after[0][1] == certificate.verification_token
    assert transfer_request is not None
    assert transfer_request.status == "approved"


@pytest.mark.asyncio
async def test_admin_denies_transfer_without_changing_membership(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_deny@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_deny@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Target Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    create_resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    request_id = create_resp.json()["data"]["id"]

    deny_resp = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{request_id}/deny",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deny_resp.status_code == 200
    assert deny_resp.json()["data"]["status"] == "denied"

    current_batch_resp = await client.get(
        "/api/v1/users/me/batch",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert current_batch_resp.status_code == 200
    assert current_batch_resp.json()["data"]["batch"]["id"] == source_batch_id


@pytest.mark.asyncio
async def test_admin_cannot_approve_already_resolved_transfer_request(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_transfer_resolved@example.com", role="admin")
    student, student_token = await _make_user(db, "student_transfer_resolved@example.com")
    program = await _make_program(db)
    await _enroll_in_program(db, student, program)

    now = datetime.now(UTC)
    open_window = {
        "enrollment_opens_at": _iso(now - timedelta(days=1)),
        "enrollment_closes_at": _iso(now + timedelta(days=1)),
    }
    source_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Source Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    target_batch_id = (
        await client.post(
            "/api/v1/admin/batches",
            json=_batch_payload(program.id, title="Target Cohort", **open_window),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]["id"]
    await client.post(
        "/api/v1/users/me/batch",
        json={"batch_id": source_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    create_resp = await client.post(
        "/api/v1/users/me/batch-transfer-requests",
        json={"to_batch_id": target_batch_id},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    request_id = create_resp.json()["data"]["id"]

    deny_resp = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{request_id}/deny",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deny_resp.status_code == 200

    approve_resp = await client.post(
        f"/api/v1/admin/batch-transfer-requests/{request_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_resp.status_code == 409
    assert approve_resp.json()["error"]["code"] == "BATCH_TRANSFER_REQUEST_ALREADY_RESOLVED"


@pytest.mark.asyncio
async def test_student_cannot_access_admin_batch_endpoints(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_guard@example.com", role="admin")
    student, student_token = await _make_user(db, "student_guard@example.com")
    program = await _make_program(db)

    create = await client.post(
        "/api/v1/admin/batches",
        json=_batch_payload(program.id),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    batch_id = create.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/admin/batches/{batch_id}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403
