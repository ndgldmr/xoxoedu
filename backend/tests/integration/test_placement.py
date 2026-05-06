"""Integration tests for AL-BE-4 — placement test, attempt submission, and admin overrides."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.placement import PlacementAttempt, PlacementResult
from app.db.models.program import Program, ProgramEnrollment
from app.db.models.user import User
from app.modules.placement.service import _PLACEMENT_QUESTIONS


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


async def _get_or_create_program(
    db: AsyncSession, code: str, title: str
) -> Program:
    """Return the program with the given code, creating it if absent.

    Using get-or-create rather than a bare insert avoids unique-constraint
    failures when multiple tests within the same DB session need OC / PT / FE.
    """
    result = await db.execute(select(Program).where(Program.code == code))
    program = result.scalar_one_or_none()
    if program is None:
        program = Program(code=code, title=title, is_active=True)
        db.add(program)
        await db.commit()
        await db.refresh(program)
    return program


async def _seed_programs(db: AsyncSession) -> dict[str, Program]:
    """Seed the three launch programs and return them keyed by code."""
    oc = await _get_or_create_program(db, "OC", "Online Communication")
    pt = await _get_or_create_program(db, "PT", "Pronunciation Training")
    fe = await _get_or_create_program(db, "FE", "Fluent English")
    return {"OC": oc, "PT": pt, "FE": fe}


def _all_correct_answers() -> dict[str, list[str]]:
    return {q["id"]: [q["correct"]] for q in _PLACEMENT_QUESTIONS}


def _all_wrong_answers() -> dict[str, list[str]]:
    wrong: dict[str, list[str]] = {}
    for q in _PLACEMENT_QUESTIONS:
        other = next(o["id"] for o in q["options"] if o["id"] != q["correct"])
        wrong[q["id"]] = [other]
    return wrong


def _partial_correct_answers(n_correct: int) -> dict[str, list[str]]:
    """Return answers with exactly ``n_correct`` questions answered correctly."""
    answers: dict[str, list[str]] = {}
    for i, q in enumerate(_PLACEMENT_QUESTIONS):
        if i < n_correct:
            answers[q["id"]] = [q["correct"]]
        else:
            other = next(o["id"] for o in q["options"] if o["id"] != q["correct"])
            answers[q["id"]] = [other]
    return answers


# ── Placement test definition ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_active_placement_test(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, f"student_fetch_{uuid.uuid4().hex[:6]}@example.com")
    resp = await client.get(
        "/api/v1/placement-tests/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["version"] == "v1"
    assert body["total_questions"] == 25
    assert len(body["questions"]) == 25
    # Correct answers must never be present in the response
    for q in body["questions"]:
        assert "correct" not in q
        assert "correct_answers" not in q


@pytest.mark.asyncio
async def test_fetch_placement_test_unauthenticated(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.get("/api/v1/placement-tests/current")
    assert resp.status_code == 401


# ── Submission — core flow ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_creates_attempt_and_result(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_programs(db)
    student, token = await _make_user(db, f"submit_core_{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    # PlacementAttempt row
    attempt_count = await db.scalar(
        select(func.count()).where(PlacementAttempt.user_id == student.id)
    )
    assert attempt_count == 1

    # PlacementResult row
    result_count = await db.scalar(
        select(func.count()).where(PlacementResult.user_id == student.id)
    )
    assert result_count == 1


@pytest.mark.asyncio
async def test_submit_unauthenticated_rejected(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
    )
    assert resp.status_code == 401


# ── Band routing ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_low_scorer_assigned_oc(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_programs(db)
    _, token = await _make_user(db, f"low_scorer_{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_wrong_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["raw_score"] == 0
    assert data["program_code"] == "OC"
    assert data["level"] == "a2_or_below"


@pytest.mark.asyncio
async def test_mid_scorer_assigned_pt(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_programs(db)
    _, token = await _make_user(db, f"mid_scorer_{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _partial_correct_answers(13)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["raw_score"] == 13
    assert data["program_code"] == "PT"
    assert data["level"] == "b1_to_b2"


@pytest.mark.asyncio
async def test_high_scorer_assigned_fe(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_programs(db)
    _, token = await _make_user(db, f"high_scorer_{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["raw_score"] == 25
    assert data["program_code"] == "FE"
    assert data["level"] == "b2_plus"


# ── Program enrollment management ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_creates_program_enrollment(client: AsyncClient, db: AsyncSession) -> None:
    programs = await _seed_programs(db)
    student, token = await _make_user(db, f"enroll_create_{uuid.uuid4().hex[:6]}@example.com")

    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )

    active_count = await db.scalar(
        select(func.count()).where(
            ProgramEnrollment.user_id == student.id,
            ProgramEnrollment.status == "active",
        )
    )
    assert active_count == 1


@pytest.mark.asyncio
async def test_repeated_submit_leaves_one_active_enrollment(
    client: AsyncClient, db: AsyncSession
) -> None:
    await _seed_programs(db)
    student, token = await _make_user(db, f"repeat_submit_{uuid.uuid4().hex[:6]}@example.com")

    # First submission → OC
    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_wrong_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Second submission → FE (band changes)
    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )

    active_count = await db.scalar(
        select(func.count()).where(
            ProgramEnrollment.user_id == student.id,
            ProgramEnrollment.status == "active",
        )
    )
    assert active_count == 1

    # The old OC enrollment should now be suspended
    suspended_count = await db.scalar(
        select(func.count()).where(
            ProgramEnrollment.user_id == student.id,
            ProgramEnrollment.status == "suspended",
        )
    )
    assert suspended_count == 1


@pytest.mark.asyncio
async def test_same_band_reactivates_existing_enrollment(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Re-submitting within the same band should UPDATE the row, not INSERT a duplicate."""
    await _seed_programs(db)
    student, token = await _make_user(db, f"same_band_{uuid.uuid4().hex[:6]}@example.com")

    # Two submissions, both scoring FE
    for _ in range(2):
        resp = await client.post(
            "/api/v1/placement-attempts",
            json={"answers": _all_correct_answers()},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    # Still exactly one enrollment row for this student+program combination
    total_fe_enrollments = await db.scalar(
        select(func.count())
        .select_from(ProgramEnrollment)
        .join(Program, Program.id == ProgramEnrollment.program_id)
        .where(
            ProgramEnrollment.user_id == student.id,
            Program.code == "FE",
        )
    )
    assert total_fe_enrollments == 1


# ── Student result endpoint ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_my_result_before_submit_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, f"no_result_{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.get(
        "/api/v1/users/me/placement-result",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NO_PLACEMENT_RESULT"


@pytest.mark.asyncio
async def test_get_my_result_after_submit(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_programs(db)
    _, token = await _make_user(db, f"has_result_{uuid.uuid4().hex[:6]}@example.com")

    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        "/api/v1/users/me/placement-result",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["level"] == "b2_plus"
    assert data["program_code"] == "FE"
    assert data["is_override"] is False


# ── Admin endpoints ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_list_placement_results(client: AsyncClient, db: AsyncSession) -> None:
    await _seed_programs(db)
    _, student_token = await _make_user(db, f"list_student_{uuid.uuid4().hex[:6]}@example.com")
    _, admin_token = await _make_user(
        db, f"list_admin_{uuid.uuid4().hex[:6]}@example.com", role="admin"
    )

    # Create a result to list
    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_correct_answers()},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    resp = await client.get(
        "/api/v1/admin/placement-results",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    results = resp.json()["data"]
    assert len(results) >= 1
    # Admin view includes student identity and scoring metadata
    first = results[0]
    assert "user_email" in first
    assert "raw_score" in first
    assert "max_score" in first
    assert "score_percent" in first


@pytest.mark.asyncio
async def test_student_cannot_access_admin_list(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, f"no_admin_{uuid.uuid4().hex[:6]}@example.com")
    resp = await client.get(
        "/api/v1/admin/placement-results",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_override_changes_program(client: AsyncClient, db: AsyncSession) -> None:
    programs = await _seed_programs(db)
    student, student_token = await _make_user(
        db, f"override_student_{uuid.uuid4().hex[:6]}@example.com"
    )
    _, admin_token = await _make_user(
        db, f"override_admin_{uuid.uuid4().hex[:6]}@example.com", role="admin"
    )

    # Student completes placement → OC (all wrong)
    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_wrong_answers()},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    # Fetch the result id
    result_row = await db.scalar(
        select(PlacementResult).where(PlacementResult.user_id == student.id)
    )
    assert result_row is not None

    # Admin overrides to PT
    resp = await client.patch(
        f"/api/v1/admin/placement-results/{result_row.id}",
        json={"program_id": str(programs["PT"].id), "level": "b1_to_b2"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_override"] is True
    assert data["level"] == "b1_to_b2"
    assert data["program_code"] == "PT"


@pytest.mark.asyncio
async def test_admin_override_swaps_enrollment(client: AsyncClient, db: AsyncSession) -> None:
    programs = await _seed_programs(db)
    student, student_token = await _make_user(
        db, f"swap_student_{uuid.uuid4().hex[:6]}@example.com"
    )
    _, admin_token = await _make_user(
        db, f"swap_admin_{uuid.uuid4().hex[:6]}@example.com", role="admin"
    )

    # Student placed into OC (all wrong)
    await client.post(
        "/api/v1/placement-attempts",
        json={"answers": _all_wrong_answers()},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    result_row = await db.scalar(
        select(PlacementResult).where(PlacementResult.user_id == student.id)
    )

    # Admin overrides to FE
    await client.patch(
        f"/api/v1/admin/placement-results/{result_row.id}",
        json={"program_id": str(programs["FE"].id), "level": "b2_plus"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Only one active enrollment, and it must be FE
    active = await db.execute(
        select(ProgramEnrollment)
        .join(Program, Program.id == ProgramEnrollment.program_id)
        .where(
            ProgramEnrollment.user_id == student.id,
            ProgramEnrollment.status == "active",
        )
    )
    active_rows = active.scalars().all()
    assert len(active_rows) == 1
    fe_prog = await db.get(Program, active_rows[0].program_id)
    assert fe_prog.code == "FE"


@pytest.mark.asyncio
async def test_admin_override_nonexistent_result_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    programs = await _seed_programs(db)
    _, admin_token = await _make_user(
        db, f"miss_admin_{uuid.uuid4().hex[:6]}@example.com", role="admin"
    )

    resp = await client.patch(
        f"/api/v1/admin/placement-results/{uuid.uuid4()}",
        json={"program_id": str(programs["OC"].id), "level": "a2_or_below"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PLACEMENT_RESULT_NOT_FOUND"
