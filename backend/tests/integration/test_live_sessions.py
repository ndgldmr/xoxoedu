"""Integration tests for Sprint 11B — live sessions and calendar endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.batch import Batch, BatchEnrollment
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
        title="Live Session Test Program",
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
        title="Test Batch",
        status=status,
        timezone="UTC",
        starts_at=datetime(2026, 1, 1, tzinfo=UTC),
        ends_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def _enroll_student_in_batch(
    db: AsyncSession, batch: Batch, user: User
) -> None:
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


def _session_payload(**overrides: object) -> dict:
    base: dict = {
        "title": "Week 1 Q&A",
        "starts_at": "2026-08-01T14:00:00Z",
        "ends_at": "2026-08-01T15:00:00Z",
        "timezone": "America/New_York",
    }
    base.update(overrides)
    return base


# ── Admin — create live session ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_creates_live_session(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_ls_create@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "fake-task-id"
        mock_task.apply_async.return_value = mock_result

        resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(provider="zoom", join_url="https://zoom.us/j/123"),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Week 1 Q&A"
    assert data["status"] == "scheduled"
    assert data["batch_id"] == str(batch.id)
    assert data["provider"] == "zoom"
    assert data["join_url"] == "https://zoom.us/j/123"


@pytest.mark.asyncio
async def test_student_cannot_create_live_session(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, "admin_ls_guard@example.com", role="admin")
    student, token = await _make_user(db, "student_ls_guard@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    resp = await client.post(
        f"/api/v1/admin/batches/{batch.id}/live-sessions",
        json=_session_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_live_session_on_archived_batch_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_arch@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id, status="archived")

    resp = await client.post(
        f"/api/v1/admin/batches/{batch.id}/live-sessions",
        json=_session_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_ARCHIVED"


@pytest.mark.asyncio
async def test_create_live_session_ends_before_starts_returns_422(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_dates@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    resp = await client.post(
        f"/api/v1/admin/batches/{batch.id}/live-sessions",
        json=_session_payload(
            starts_at="2026-08-01T15:00:00Z",
            ends_at="2026-08-01T14:00:00Z",
        ),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ── Admin — list live sessions ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_lists_live_sessions(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin_ls_list@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="t1")
        for i in range(3):
            await client.post(
                f"/api/v1/admin/batches/{batch.id}/live-sessions",
                json=_session_payload(
                    title=f"Session {i}",
                    starts_at=f"2026-08-0{i + 1}T14:00:00Z",
                    ends_at=f"2026-08-0{i + 1}T15:00:00Z",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )

    resp = await client.get(
        f"/api/v1/admin/batches/{batch.id}/live-sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 3


@pytest.mark.asyncio
async def test_canceled_sessions_excluded_by_default(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_canceled@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        create_resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_id = create_resp.json()["data"]["id"]

    # Cancel the session
    await client.delete(
        f"/api/v1/admin/live-sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp_default = await client.get(
        f"/api/v1/admin/batches/{batch.id}/live-sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_default.status_code == 200
    assert len(resp_default.json()["data"]) == 0

    resp_with_canceled = await client.get(
        f"/api/v1/admin/batches/{batch.id}/live-sessions?include_canceled=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(resp_with_canceled.json()["data"]) == 1


# ── Admin — update live session ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_updates_live_session_title(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_update@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        create_resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_id = create_resp.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/admin/live-sessions/{session_id}",
        json={"title": "Updated Title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_session_update_reschedules_reminder_when_starts_at_changes(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_reschedule@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="original-task")
        create_resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_id = create_resp.json()["data"]["id"]
    original_call_count = mt.apply_async.call_count

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt2, \
         patch("app.modules.batches.live_session_service._revoke_reminder") as mock_revoke:
        mt2.apply_async.return_value = MagicMock(id="new-task")
        resp = await client.patch(
            f"/api/v1/admin/live-sessions/{session_id}",
            json={
                "starts_at": "2026-09-01T10:00:00Z",
                "ends_at": "2026-09-01T11:00:00Z",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    mock_revoke.assert_called_once()
    mt2.apply_async.assert_called_once()


# ── Admin — cancel live session ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_cancels_live_session(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_cancel@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        create_resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_id = create_resp.json()["data"]["id"]

    resp = await client.delete(
        f"/api/v1/admin/live-sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "canceled"


@pytest.mark.asyncio
async def test_cancel_already_canceled_session_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin_ls_dblcancel@example.com", role="admin")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        create_resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_id = create_resp.json()["data"]["id"]

    await client.delete(
        f"/api/v1/admin/live-sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.delete(
        f"/api/v1/admin/live-sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LIVE_SESSION_CANCELED"


# ── Student — calendar ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_returns_upcoming_sessions_for_enrolled_student(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_cal@example.com", role="admin")
    student, student_token = await _make_user(db, "student_cal@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_student_in_batch(db, batch, student)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(starts_at="2099-01-01T10:00:00Z", ends_at="2099-01-01T11:00:00Z"),
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    resp = await client.get(
        "/api/v1/users/me/calendar",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Week 1 Q&A"
    assert data[0]["batch_id"] == str(batch.id)
    assert data[0]["batch_title"] == "Test Batch"


@pytest.mark.asyncio
async def test_calendar_excludes_sessions_from_other_batches(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_cal2@example.com", role="admin")
    student, student_token = await _make_user(db, "student_cal2@example.com")
    program = await _make_program(db)

    # Batch the student is enrolled in
    enrolled_batch = await _make_batch(db, program.id)
    await _enroll_student_in_batch(db, enrolled_batch, student)

    # Batch the student is NOT in
    other_batch = await _make_batch(db, program.id)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        for batch_id in (enrolled_batch.id, other_batch.id):
            await client.post(
                f"/api/v1/admin/batches/{batch_id}/live-sessions",
                json=_session_payload(starts_at="2099-02-01T10:00:00Z", ends_at="2099-02-01T11:00:00Z"),
                headers={"Authorization": f"Bearer {admin_token}"},
            )

    resp = await client.get(
        "/api/v1/users/me/calendar",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    # Only the session from the enrolled batch should appear
    assert len(resp.json()["data"]) == 1


@pytest.mark.asyncio
async def test_calendar_excludes_canceled_sessions(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_cal3@example.com", role="admin")
    student, student_token = await _make_user(db, "student_cal3@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_student_in_batch(db, batch, student)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        create_resp = await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(starts_at="2099-03-01T10:00:00Z", ends_at="2099-03-01T11:00:00Z"),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    session_id = create_resp.json()["data"]["id"]

    await client.delete(
        f"/api/v1/admin/live-sessions/{session_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    resp = await client.get(
        "/api/v1/users/me/calendar",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 0


# ── Student — iCal export ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ical_export_returns_valid_content(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(db, "admin_ical@example.com", role="admin")
    student, student_token = await _make_user(db, "student_ical@example.com")
    program = await _make_program(db)
    batch = await _make_batch(db, program.id)
    await _enroll_student_in_batch(db, batch, student)

    with patch("app.modules.batches.tasks.send_live_session_reminder") as mt:
        mt.apply_async.return_value = MagicMock(id="t1")
        await client.post(
            f"/api/v1/admin/batches/{batch.id}/live-sessions",
            json=_session_payload(
                starts_at="2099-04-01T10:00:00Z",
                ends_at="2099-04-01T11:00:00Z",
                join_url="https://zoom.us/j/456",
            ),
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    resp = await client.get(
        "/api/v1/users/me/calendar.ics",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers["content-type"]
    body = resp.text
    assert "BEGIN:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body
    assert "DTSTART:20990401T100000Z" in body
    assert "SUMMARY:Week 1 Q&A" in body
    assert "URL:https://zoom.us/j/456" in body
    assert "END:VCALENDAR" in body


@pytest.mark.asyncio
async def test_ical_export_empty_when_no_sessions(
    client: AsyncClient, db: AsyncSession
) -> None:
    _, student_token = await _make_user(db, "student_ical_empty@example.com")

    resp = await client.get(
        "/api/v1/users/me/calendar.ics",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    assert "BEGIN:VEVENT" not in resp.text
    assert "BEGIN:VCALENDAR" in resp.text
