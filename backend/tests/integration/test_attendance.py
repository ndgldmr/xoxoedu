"""Integration tests for Sprint 11C — attendance marking and batch reporting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.batch import Batch, BatchEnrollment
from app.db.models.live_session import LiveSession
from app.db.models.program import Program, ProgramEnrollment
from app.db.models.user import User


# ── Fixture helpers ────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, *, role: str = "student"
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
        title="Attendance Test Program",
        is_active=True,
    )
    db.add(program)
    await db.commit()
    await db.refresh(program)
    return program


async def _make_batch(
    db: AsyncSession, program_id: uuid.UUID, status: str = "active"
) -> Batch:
    batch = Batch(
        program_id=program_id,
        title="Attendance Test Batch",
        status=status,
        timezone="UTC",
        starts_at=datetime(2026, 1, 1, tzinfo=UTC),
        ends_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def _enroll_in_batch(
    db: AsyncSession, batch: Batch, user: User
) -> BatchEnrollment:
    pe = ProgramEnrollment(
        user_id=user.id,
        program_id=batch.program_id,
        status="active",
    )
    db.add(pe)
    await db.flush()
    be = BatchEnrollment(
        batch_id=batch.id,
        user_id=user.id,
        program_enrollment_id=pe.id,
    )
    db.add(be)
    await db.commit()
    await db.refresh(be)
    return be


async def _make_live_session(
    db: AsyncSession,
    batch_id: uuid.UUID,
    title: str = "Test Session",
) -> LiveSession:
    session = LiveSession(
        batch_id=batch_id,
        title=title,
        starts_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 3, 1, 11, 0, tzinfo=UTC),
        timezone="UTC",
        status="scheduled",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── POST /live-sessions/{id}/attendance ────────────────────────────────────────

@pytest.mark.asyncio
async def test_student_marks_own_attendance(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, "att_admin1@example.com", role="admin")
    student, token = await _make_user(db, "att_student1@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, student)
    session = await _make_live_session(db, batch.id)

    resp = await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["session_id"] == str(session.id)
    assert data["user_id"] == str(student.id)
    assert data["status"] == "present"


@pytest.mark.asyncio
async def test_mark_attendance_twice_updates_existing_row(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Idempotent upsert: second write updates status, not creates a duplicate."""
    admin, _ = await _make_user(db, "att_admin2@example.com", role="admin")
    student, token = await _make_user(db, "att_student2@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, student)
    session = await _make_live_session(db, batch.id)

    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "late"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "late"

    # Report should show exactly one record for this student/session.
    admin_user, admin_token = await _make_user(
        db, "att_admin2b@example.com", role="admin"
    )
    report_resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    sessions_data = report_resp.json()["data"]["session_summaries"]
    assert sessions_data[0]["late"] == 1
    assert sessions_data[0]["present"] == 0


@pytest.mark.asyncio
async def test_admin_marks_attendance_for_another_student(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_admin3@example.com", role="admin")
    student, _ = await _make_user(db, "att_student3@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, student)
    session = await _make_live_session(db, batch.id)

    resp = await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "absent", "user_id": str(student.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["user_id"] == str(student.id)
    assert resp.json()["data"]["status"] == "absent"


@pytest.mark.asyncio
async def test_student_cannot_mark_another_students_attendance(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, "att_admin4@example.com", role="admin")
    student_a, token_a = await _make_user(db, "att_stuA@example.com")
    student_b, _ = await _make_user(db, "att_stuB@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, student_a)
    await _enroll_in_batch(db, batch, student_b)
    session = await _make_live_session(db, batch.id)

    resp = await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present", "user_id": str(student_b.id)},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mark_attendance_for_non_member_returns_403(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_admin5@example.com", role="admin")
    outsider, _ = await _make_user(db, "att_outsider@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    session = await _make_live_session(db, batch.id)

    resp = await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present", "user_id": str(outsider.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NOT_A_BATCH_MEMBER"


@pytest.mark.asyncio
async def test_mark_attendance_unknown_session_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, token = await _make_user(db, "att_student6@example.com")

    resp = await client.post(
        f"/api/v1/admin/live-sessions/{uuid.uuid4()}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "LIVE_SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, "att_admin7@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    session = await _make_live_session(db, batch.id)

    resp = await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
    )
    assert resp.status_code in (400, 401, 403)


# ── GET /admin/batches/{id}/attendance ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_attendance_report_matches_underlying_records(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin1@example.com", role="admin")
    s1, t1 = await _make_user(db, "att_rs1@example.com")
    s2, t2 = await _make_user(db, "att_rs2@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, s1)
    await _enroll_in_batch(db, batch, s2)
    session = await _make_live_session(db, batch.id, title="Week 1")

    # s1 → present, s2 → absent
    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "absent"},
        headers={"Authorization": f"Bearer {t2}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    report = resp.json()["data"]

    assert report["total_sessions"] == 1
    assert report["total_members"] == 2

    sess_summary = report["session_summaries"][0]
    assert sess_summary["present"] == 1
    assert sess_summary["absent"] == 1
    assert sess_summary["late"] == 0
    assert sess_summary["unmarked"] == 0
    assert sess_summary["title"] == "Week 1"
    assert sess_summary["attendance_rate"] == 0.5  # 1 present / 2 members

    # Student summaries
    student_map = {s["user_id"]: s for s in report["student_summaries"]}
    assert student_map[str(s1.id)]["present_count"] == 1
    assert student_map[str(s2.id)]["absent_count"] == 1

    # Overall rate: 1 attended (present) / (1 session × 2 members) = 0.5
    assert report["overall_attendance_rate"] == 0.5


@pytest.mark.asyncio
async def test_report_counts_late_as_attended_in_rate(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin2@example.com", role="admin")
    student, token = await _make_user(db, "att_rs_late@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, student)
    session = await _make_live_session(db, batch.id)

    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "late"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    report = resp.json()["data"]
    assert report["overall_attendance_rate"] == 1.0
    assert report["session_summaries"][0]["attendance_rate"] == 1.0


@pytest.mark.asyncio
async def test_report_counts_unmarked_students(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin3@example.com", role="admin")
    s1, t1 = await _make_user(db, "att_rs_unm1@example.com")
    s2, _ = await _make_user(db, "att_rs_unm2@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, s1)
    await _enroll_in_batch(db, batch, s2)
    session = await _make_live_session(db, batch.id)

    # Only s1 marks attendance
    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {t1}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    sess_summary = resp.json()["data"]["session_summaries"][0]
    assert sess_summary["present"] == 1
    assert sess_summary["unmarked"] == 1


@pytest.mark.asyncio
async def test_report_excludes_students_outside_batch(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin4@example.com", role="admin")
    member, token = await _make_user(db, "att_member@example.com")
    outsider, _ = await _make_user(db, "att_outsider4@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, member)
    session = await _make_live_session(db, batch.id)

    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    report = resp.json()["data"]
    # Only the batch member appears in student summaries
    assert report["total_members"] == 1
    assert all(
        s["user_id"] != str(outsider.id)
        for s in report["student_summaries"]
    )


@pytest.mark.asyncio
async def test_report_filtered_by_session_id(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin5@example.com", role="admin")
    student, token = await _make_user(db, "att_rs_filt@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, student)
    sess1 = await _make_live_session(db, batch.id, title="Week 1")
    sess2 = await _make_live_session(db, batch.id, title="Week 2")

    await client.post(
        f"/api/v1/admin/live-sessions/{sess1.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        f"/api/v1/admin/live-sessions/{sess2.id}/attendance",
        json={"status": "absent"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance?session_id={sess1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    report = resp.json()["data"]
    assert report["total_sessions"] == 1
    assert report["session_summaries"][0]["title"] == "Week 1"


@pytest.mark.asyncio
async def test_report_filtered_by_user_id(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin6@example.com", role="admin")
    s1, t1 = await _make_user(db, "att_rf1@example.com")
    s2, t2 = await _make_user(db, "att_rf2@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, s1)
    await _enroll_in_batch(db, batch, s2)
    session = await _make_live_session(db, batch.id)

    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "absent"},
        headers={"Authorization": f"Bearer {t2}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance?user_id={s1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    report = resp.json()["data"]
    assert report["total_members"] == 1
    assert report["student_summaries"][0]["user_id"] == str(s1.id)


@pytest.mark.asyncio
async def test_report_filtered_by_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin7@example.com", role="admin")
    s1, t1 = await _make_user(db, "att_rfs1@example.com")
    s2, t2 = await _make_user(db, "att_rfs2@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_in_batch(db, batch, s1)
    await _enroll_in_batch(db, batch, s2)
    session = await _make_live_session(db, batch.id)

    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "present"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    await client.post(
        f"/api/v1/admin/live-sessions/{session.id}/attendance",
        json={"status": "absent"},
        headers={"Authorization": f"Bearer {t2}"},
    )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance?status=present",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    report = resp.json()["data"]
    sess_summary = report["session_summaries"][0]
    assert sess_summary["present"] == 1
    assert sess_summary["absent"] == 0  # absent row excluded by filter


@pytest.mark.asyncio
async def test_report_student_cannot_access(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, "att_radmin8@example.com", role="admin")
    student, token = await _make_user(db, "att_rstu8@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_report_unknown_batch_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, admin_token = await _make_user(db, "att_radmin9@example.com", role="admin")

    resp = await client.get(
        f"/api/v1/admin/batches/{uuid.uuid4()}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "BATCH_NOT_FOUND"


@pytest.mark.asyncio
async def test_report_empty_when_no_sessions(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "att_radmin10@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/attendance",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["total_sessions"] == 0
    assert report["total_members"] == 0
    assert report["overall_attendance_rate"] == 0.0
    assert report["session_summaries"] == []
    assert report["student_summaries"] == []
