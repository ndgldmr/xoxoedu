"""Integration tests for AL-BE-2 — programs, curriculum steps, and program enrollment."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Course
from app.db.models.program import Program, ProgramEnrollment
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


async def _make_program(
    db: AsyncSession,
    code: str | None = None,
    *,
    display_order: int = 0,
    is_active: bool = True,
    cover_image_url: str | None = None,
    marketing_summary: str | None = None,
) -> Program:
    program = Program(
        code=code or f"P{uuid.uuid4().hex[:5].upper()}",
        title="Test Program",
        marketing_summary=marketing_summary,
        cover_image_url=cover_image_url,
        display_order=display_order,
        is_active=is_active,
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
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_unpublished_course(db: AsyncSession) -> Course:
    course = Course(
        title=f"Draft Course {uuid.uuid4().hex[:6]}",
        slug=uuid.uuid4().hex[:12],
        status="draft",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _enroll(
    db: AsyncSession, user: User, program: Program, status: str = "active"
) -> ProgramEnrollment:
    pe = ProgramEnrollment(user_id=user.id, program_id=program.id, status=status)
    db.add(pe)
    await db.commit()
    await db.refresh(pe)
    return pe


# ── Admin — program CRUD ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_creates_program(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_create@example.com", role="admin")
    code = f"TP{uuid.uuid4().hex[:4].upper()}"

    resp = await client.post(
        "/api/v1/admin/programs",
        json={"code": code, "title": "Fluent English"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["code"] == code
    assert data["title"] == "Fluent English"
    assert data["display_order"] == 0
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_admin_creates_program_with_public_marketing_fields(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, "admin_prog_marketing@example.com", role="admin")

    resp = await client.post(
        "/api/v1/admin/programs",
        json={
            "code": f"PM{uuid.uuid4().hex[:4].upper()}",
            "title": "Purpose Pathway",
            "marketing_summary": "A guided pathway for purposeful English practice.",
            "cover_image_url": "https://example.com/program.jpg",
            "display_order": 3,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["marketing_summary"] == "A guided pathway for purposeful English practice."
    assert data["cover_image_url"] == "https://example.com/program.jpg"
    assert data["display_order"] == 3


@pytest.mark.asyncio
async def test_admin_cannot_create_duplicate_code(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_dup@example.com", role="admin")
    await _make_program(db, code="DUPX")

    resp = await client.post(
        "/api/v1/admin/programs",
        json={"code": "DUPX", "title": "Duplicate"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_student_cannot_create_program(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "student_prog_create@example.com")

    resp = await client.post(
        "/api/v1/admin/programs",
        json={"code": "OC", "title": "Online Communication"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_lists_programs(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_list@example.com", role="admin")
    for i in range(3):
        await _make_program(db)

    resp = await client.get(
        "/api/v1/admin/programs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 3


@pytest.mark.asyncio
async def test_admin_filters_active_programs(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_filter@example.com", role="admin")

    # Create one active and one inactive program
    active_prog = await _make_program(db)
    inactive_prog = await _make_program(db)
    inactive_prog.is_active = False
    await db.commit()

    resp = await client.get(
        "/api/v1/admin/programs?is_active=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["data"]]
    assert str(active_prog.id) in ids
    assert str(inactive_prog.id) not in ids


@pytest.mark.asyncio
async def test_admin_gets_program_with_steps(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_get@example.com", role="admin")
    program = await _make_program(db)

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(program.id)
    assert "steps" in data
    assert data["steps"] == []


@pytest.mark.asyncio
async def test_admin_gets_unknown_program_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, "admin_prog_404@example.com", role="admin")

    resp = await client.get(
        f"/api/v1/admin/programs/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_updates_program(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_update@example.com", role="admin")
    program = await _make_program(db)

    resp = await client.patch(
        f"/api/v1/admin/programs/{program.id}",
        json={"title": "Updated Title", "is_active": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["title"] == "Updated Title"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_admin_updates_program_public_fields(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_prog_update_public@example.com", role="admin")
    program = await _make_program(db)

    resp = await client.patch(
        f"/api/v1/admin/programs/{program.id}",
        json={
            "marketing_summary": "Updated public summary",
            "cover_image_url": "https://example.com/updated.jpg",
            "display_order": 8,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["marketing_summary"] == "Updated public summary"
    assert data["cover_image_url"] == "https://example.com/updated.jpg"
    assert data["display_order"] == 8


# ── Admin — curriculum steps ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_adds_step(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_add@example.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)

    resp = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["program_id"] == str(program.id)
    assert data["course_id"] == str(course.id)
    assert data["position"] == 1
    assert data["is_required"] is True


@pytest.mark.asyncio
async def test_admin_cannot_add_duplicate_position(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_duppos@example.com", role="admin")
    program = await _make_program(db)
    course1 = await _make_course(db)
    course2 = await _make_course(db)

    await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course1.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course2.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_admin_cannot_add_duplicate_course(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_dupcourse@example.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)

    await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course.id), "position": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_admin_lists_steps_ordered_by_position(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, "admin_step_list@example.com", role="admin")
    program = await _make_program(db)
    courses = [await _make_course(db) for _ in range(3)]

    for pos, course in zip([3, 1, 2], courses):
        await client.post(
            f"/api/v1/admin/programs/{program.id}/steps",
            json={"course_id": str(course.id), "position": pos},
            headers={"Authorization": f"Bearer {token}"},
        )

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/steps",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    positions = [s["position"] for s in resp.json()["data"]]
    assert positions == [1, 2, 3]


@pytest.mark.asyncio
async def test_admin_deletes_step(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_delete@example.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)

    add_resp = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    step_id = add_resp.json()["data"]["id"]

    del_resp = await client.delete(
        f"/api/v1/admin/programs/{program.id}/steps/{step_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["data"]["deleted"] is True

    list_resp = await client.get(
        f"/api/v1/admin/programs/{program.id}/steps",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.json()["data"] == []


@pytest.mark.asyncio
async def test_admin_reorders_steps(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_reorder@example.com", role="admin")
    program = await _make_program(db)
    courses = [await _make_course(db) for _ in range(3)]

    step_ids = []
    for pos, course in enumerate(courses, start=1):
        r = await client.post(
            f"/api/v1/admin/programs/{program.id}/steps",
            json={"course_id": str(course.id), "position": pos},
            headers={"Authorization": f"Bearer {token}"},
        )
        step_ids.append(r.json()["data"]["id"])

    # Reverse the order
    reversed_ids = list(reversed(step_ids))
    resp = await client.put(
        f"/api/v1/admin/programs/{program.id}/steps/reorder",
        json={"step_ids": reversed_ids},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    positions = {item["id"]: item["position"] for item in resp.json()["data"]}
    assert positions[reversed_ids[0]] == 1
    assert positions[reversed_ids[1]] == 2
    assert positions[reversed_ids[2]] == 3


@pytest.mark.asyncio
async def test_reorder_with_missing_ids_rejected(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_reorder_bad@example.com", role="admin")
    program = await _make_program(db)
    courses = [await _make_course(db) for _ in range(2)]

    step_ids = []
    for pos, course in enumerate(courses, start=1):
        r = await client.post(
            f"/api/v1/admin/programs/{program.id}/steps",
            json={"course_id": str(course.id), "position": pos},
            headers={"Authorization": f"Bearer {token}"},
        )
        step_ids.append(r.json()["data"]["id"])

    # Supply only one of two step IDs
    resp = await client.put(
        f"/api/v1/admin/programs/{program.id}/steps/reorder",
        json={"step_ids": [step_ids[0]]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reorder_with_extra_ids_rejected(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "admin_step_reorder_extra@example.com", role="admin")
    program = await _make_program(db)
    course = await _make_course(db)

    r = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(course.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    step_id = r.json()["data"]["id"]

    resp = await client.put(
        f"/api/v1/admin/programs/{program.id}/steps/reorder",
        json={"step_ids": [step_id, str(uuid.uuid4())]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ── Admin — program enrollments ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_enrolls_student(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin_enroll@example.com", role="admin")
    student, _ = await _make_user(db, "student_enroll@example.com")
    program = await _make_program(db)

    resp = await client.post(
        f"/api/v1/admin/users/{student.id}/program-enrollments",
        json={"program_id": str(program.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["user_id"] == str(student.id)
    assert data["program_id"] == str(program.id)
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_second_active_enrollment_rejected(client: AsyncClient, db: AsyncSession) -> None:
    """A student cannot have two active program enrollments simultaneously."""
    _, admin_token = await _make_user(db, "admin_double_enroll@example.com", role="admin")
    student, _ = await _make_user(db, "student_double@example.com")
    program1 = await _make_program(db)
    program2 = await _make_program(db)

    resp1 = await client.post(
        f"/api/v1/admin/users/{student.id}/program-enrollments",
        json={"program_id": str(program1.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/api/v1/admin/users/{student.id}/program-enrollments",
        json={"program_id": str(program2.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "DUPLICATE_ACTIVE_PROGRAM_ENROLLMENT"


@pytest.mark.asyncio
async def test_admin_lists_student_enrollments(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin_list_enroll@example.com", role="admin")
    student, _ = await _make_user(db, "student_list_enroll@example.com")
    prog1 = await _make_program(db)
    prog2 = await _make_program(db)

    # Seed one canceled + one active enrollment directly (bypass the one-active guard)
    await _enroll(db, student, prog1, status="canceled")
    await _enroll(db, student, prog2, status="active")

    resp = await client.get(
        f"/api/v1/admin/users/{student.id}/program-enrollments",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2


@pytest.mark.asyncio
async def test_admin_updates_enrollment_status(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin_upd_enroll@example.com", role="admin")
    student, _ = await _make_user(db, "student_upd_enroll@example.com")
    program = await _make_program(db)
    enrollment = await _enroll(db, student, program)

    resp = await client.patch(
        f"/api/v1/admin/program-enrollments/{enrollment.id}",
        json={"status": "suspended"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "suspended"


@pytest.mark.asyncio
async def test_invalid_enrollment_transition_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, admin_token = await _make_user(db, "admin_bad_trans@example.com", role="admin")
    student, _ = await _make_user(db, "student_bad_trans@example.com")
    program = await _make_program(db)
    enrollment = await _enroll(db, student, program, status="canceled")

    resp = await client.patch(
        f"/api/v1/admin/program-enrollments/{enrollment.id}",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_enrollment_not_found_returns_404(client: AsyncClient, db: AsyncSession) -> None:
    _, admin_token = await _make_user(db, "admin_enroll_404@example.com", role="admin")

    resp = await client.patch(
        f"/api/v1/admin/program-enrollments/{uuid.uuid4()}",
        json={"status": "suspended"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


# ── Student — active enrollment ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_student_reads_active_enrollment(client: AsyncClient, db: AsyncSession) -> None:
    student, student_token = await _make_user(db, "student_me_enroll@example.com")
    program = await _make_program(db)
    await _enroll(db, student, program)

    resp = await client.get(
        "/api/v1/users/me/program-enrollment",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "active"
    assert data["program_id"] == str(program.id)


@pytest.mark.asyncio
async def test_student_with_no_enrollment_gets_null(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, student_token = await _make_user(db, "student_no_enroll@example.com")

    resp = await client.get(
        "/api/v1/users/me/program-enrollment",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] is None


@pytest.mark.asyncio
async def test_student_does_not_see_historical_enrollments_in_active(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Completed/canceled enrollments must not appear as the active enrollment."""
    student, student_token = await _make_user(db, "student_hist@example.com")
    program = await _make_program(db)
    await _enroll(db, student, program, status="completed")

    resp = await client.get(
        "/api/v1/users/me/program-enrollment",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] is None


@pytest.mark.asyncio
async def test_admin_cannot_access_student_enrollment_endpoint(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, admin_token = await _make_user(db, "admin_me_enroll@example.com", role="admin")

    resp = await client.get(
        "/api/v1/users/me/program-enrollment",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403


# ── get_program includes steps ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_program_includes_ordered_steps(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/programs/{id} must return steps ordered by position."""
    _, token = await _make_user(db, "admin_prog_steps@example.com", role="admin")
    program = await _make_program(db)
    courses = [await _make_course(db) for _ in range(3)]

    for pos, course in zip([2, 3, 1], courses):
        await client.post(
            f"/api/v1/admin/programs/{program.id}/steps",
            json={"course_id": str(course.id), "position": pos},
            headers={"Authorization": f"Bearer {token}"},
        )

    resp = await client.get(
        f"/api/v1/admin/programs/{program.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    steps = resp.json()["data"]["steps"]
    assert len(steps) == 3
    assert [s["position"] for s in steps] == [1, 2, 3]


# ── Public — program discovery ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_lists_only_active_programs_in_display_order(
    client: AsyncClient, db: AsyncSession
) -> None:
    second = await _make_program(db, code="PB", display_order=2, marketing_summary="Second")
    first = await _make_program(db, code="PA", display_order=1, marketing_summary="First")
    await _make_program(db, code="PC", display_order=3, is_active=False)

    resp = await client.get("/api/v1/programs")
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert [program["id"] for program in data[:2]] == [str(first.id), str(second.id)]
    assert all(program["is_active"] is True for program in data)


@pytest.mark.asyncio
async def test_public_programs_include_only_published_course_steps(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, "admin_public_programs@example.com", role="admin")
    program = await _make_program(
        db,
        code="PP",
        display_order=1,
        marketing_summary="Purpose-built public summary",
        cover_image_url="https://example.com/program-cover.jpg",
    )
    published_course = await _make_course(db)
    draft_course = await _make_unpublished_course(db)

    add_published = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(published_course.id), "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert add_published.status_code == 201
    add_draft = await client.post(
        f"/api/v1/admin/programs/{program.id}/steps",
        json={"course_id": str(draft_course.id), "position": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert add_draft.status_code == 201

    resp = await client.get("/api/v1/programs")
    assert resp.status_code == 200

    public_program = next(item for item in resp.json()["data"] if item["id"] == str(program.id))
    assert public_program["marketing_summary"] == "Purpose-built public summary"
    assert public_program["cover_image_url"] == "https://example.com/program-cover.jpg"
    assert public_program["display_order"] == 1
    assert public_program["steps"] == [
        {
            "course_cover_image_url": None,
            "course_id": str(published_course.id),
            "course_level": "beginner",
            "course_slug": published_course.slug,
            "course_title": published_course.title,
            "is_required": True,
            "position": 1,
        }
    ]
