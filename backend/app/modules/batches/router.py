"""FastAPI router for batch management, batch enrollment, and live session endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden
from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.batches import attendance_service, live_session_service, service
from app.modules.batches.attendance_schemas import AttendanceIn, AttendanceOut
from app.modules.batches.ical import _SessionData, build_ical
from app.modules.batches.live_session_schemas import (
    CalendarSessionOut,
    LiveSessionIn,
    LiveSessionOut,
    LiveSessionUpdateIn,
)
from app.modules.batches.schemas import (
    BatchAvailabilityOut,
    BatchIn,
    BatchMemberIn,
    BatchMemberOut,
    BatchMembershipOut,
    BatchOut,
    BatchSelectionIn,
    BatchStudentProgressOut,
    BatchTransferRequestAdminOut,
    BatchTransferRequestIn,
    BatchTransferRequestStudentOut,
    BatchUpdateIn,
    StudentCourseProgressOut,
)

router = APIRouter(tags=["batches"])


# ── Admin — batch CRUD ─────────────────────────────────────────────────────────

@router.post("/admin/batches", status_code=201)
async def create_batch(
    body: BatchIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Create a new batch for a program."""
    batch = await service.create_batch(
        db,
        program_id=body.program_id,
        title=body.title,
        timezone=body.timezone,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        enrollment_opens_at=body.enrollment_opens_at,
        enrollment_closes_at=body.enrollment_closes_at,
        capacity=body.capacity,
    )
    return ok(BatchOut.model_validate(batch).model_dump())


@router.get("/admin/programs/{program_id}/batches")
async def list_batches(
    program_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List batches for a program, optionally filtered by status."""
    batches, total = await service.list_batches(db, program_id, status, skip, limit)
    return ok(
        [BatchOut.model_validate(b).model_dump() for b in batches],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/admin/batches/{batch_id}")
async def get_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Fetch a single batch by ID."""
    batch = await service.get_batch(db, batch_id)
    return ok(BatchOut.model_validate(batch).model_dump())


@router.patch("/admin/batches/{batch_id}")
async def update_batch(
    batch_id: uuid.UUID,
    body: BatchUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Partially update a batch (title, dates, capacity, status, timezone)."""
    batch = await service.update_batch(
        db,
        batch_id=batch_id,
        title=body.title,
        timezone=body.timezone,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        enrollment_opens_at=body.enrollment_opens_at,
        enrollment_closes_at=body.enrollment_closes_at,
        capacity=body.capacity,
        status=body.status,
    )
    return ok(BatchOut.model_validate(batch).model_dump())


# ── Admin — batch membership ───────────────────────────────────────────────────

@router.post("/admin/batches/{batch_id}/members", status_code=201)
async def add_member(
    batch_id: uuid.UUID,
    body: BatchMemberIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Add a student to a batch.

    If the student does not yet have a course enrollment, one is created
    automatically as part of this operation.
    """
    member = await service.add_member(db, batch_id=batch_id, user_id=body.user_id)
    return ok(BatchMemberOut.model_validate(member).model_dump())


@router.delete("/admin/batches/{batch_id}/members/{user_id}", status_code=200)
async def remove_member(
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Remove a student from a batch."""
    await service.remove_member(db, batch_id=batch_id, user_id=user_id)
    return ok({"removed": True})


@router.get("/admin/batches/{batch_id}/members")
async def list_members(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List all members of a batch with user info."""
    members, total = await service.list_members(db, batch_id, skip, limit)
    return ok(
        [BatchMemberOut.model_validate(m).model_dump() for m in members],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/admin/batches/{batch_id}/progress")
async def get_batch_progress(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Per-student lesson completion, quiz, and assignment progress for a batch.

    For each member of the batch, returns a row with:

    - ``overall_completion_pct``: mean lesson completion across all required
      program steps.
    - ``courses``: one ``StudentCourseProgressOut`` per program step with
      lesson completion percentage, best quiz score, and best published
      assignment score.

    Args:
        batch_id: UUID of the target batch.
        skip: Offset for pagination.
        limit: Page size (max 200).
        db: Injected async database session.
        _: Admin role enforcement dependency.

    Returns:
        Paginated list of ``BatchStudentProgressOut`` with ``meta.total``,
        ``meta.skip``, and ``meta.limit``.
    """
    students, total = await service.get_batch_progress_report(db, batch_id, skip, limit)
    return ok(
        [s.model_dump() for s in students],
        meta={"total": total, "skip": skip, "limit": limit},
    )


# ── Student ────────────────────────────────────────────────────────────────────

@router.get("/users/me/batches")
async def list_my_batches(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List the authenticated student's batch memberships."""
    memberships, total = await service.list_my_batches(
        db, current_user.id, skip, limit
    )
    return ok(
        [BatchMembershipOut.model_validate(m).model_dump() for m in memberships],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/users/me/batches/available")
async def list_available_batches(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """List eligible selectable batches for the student's active program."""
    available = await service.list_available_batches_for_user(db, current_user.id)
    return ok(
        [
            BatchAvailabilityOut(
                id=batch.id,
                program_id=batch.program_id,
                title=batch.title,
                status=batch.status,
                timezone=batch.timezone,
                starts_at=batch.starts_at,
                ends_at=batch.ends_at,
                enrollment_opens_at=batch.enrollment_opens_at,
                enrollment_closes_at=batch.enrollment_closes_at,
                capacity=batch.capacity,
                remaining_seats=remaining_seats,
            ).model_dump()
            for batch, remaining_seats in available
        ]
    )


@router.get("/users/me/batch")
async def get_my_current_batch(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the student's current batch selection for their active program."""
    membership = await service.get_current_batch_for_user(db, current_user.id)
    data = BatchMembershipOut.model_validate(membership).model_dump() if membership else None
    return ok(data)


@router.post("/users/me/batch", status_code=201)
async def select_batch(
    body: BatchSelectionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Select an eligible batch for the student's active program."""
    membership = await service.select_batch_for_user(db, current_user.id, body.batch_id)
    return ok(BatchMembershipOut.model_validate(membership).model_dump())


@router.post("/users/me/batch-transfer-requests", status_code=201)
async def create_transfer_request(
    body: BatchTransferRequestIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Create a batch transfer request for the authenticated student."""
    request = await service.create_transfer_request(
        db,
        current_user.id,
        body.to_batch_id,
        body.reason,
    )
    return ok(BatchTransferRequestStudentOut.model_validate(request).model_dump())


@router.get("/users/me/batch-transfer-requests")
async def list_my_transfer_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """List the authenticated student's batch transfer requests."""
    requests = await service.list_my_transfer_requests(db, current_user.id)
    return ok(
        [
            BatchTransferRequestStudentOut.model_validate(request).model_dump()
            for request in requests
        ]
    )


@router.get("/admin/batch-transfer-requests")
async def list_transfer_requests(
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List batch transfer requests for admin review."""
    requests, total = await service.list_transfer_requests(db, status, skip, limit)
    return ok(
        [
            BatchTransferRequestAdminOut.model_validate(request).model_dump()
            for request in requests
        ],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.post("/admin/batch-transfer-requests/{request_id}/approve")
async def approve_transfer_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Approve a batch transfer request and move batch membership."""
    request = await service.approve_transfer_request(db, request_id, current_user.id)
    return ok(BatchTransferRequestAdminOut.model_validate(request).model_dump())


@router.post("/admin/batch-transfer-requests/{request_id}/deny")
async def deny_transfer_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Deny a batch transfer request without changing membership."""
    request = await service.deny_transfer_request(db, request_id, current_user.id)
    return ok(BatchTransferRequestAdminOut.model_validate(request).model_dump())


# ── Admin — live sessions ──────────────────────────────────────────────────────

@router.post("/admin/batches/{batch_id}/live-sessions", status_code=201)
async def create_live_session(
    batch_id: uuid.UUID,
    body: LiveSessionIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Create a new live session under a batch and schedule a reminder."""
    session = await live_session_service.create_live_session(
        db,
        batch_id=batch_id,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        timezone=body.timezone,
        provider=body.provider,
        join_url=body.join_url,
        recording_url=body.recording_url,
    )
    return ok(LiveSessionOut.model_validate(session).model_dump())


@router.get("/admin/batches/{batch_id}/live-sessions")
async def list_live_sessions(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    include_canceled: bool = Query(False),
) -> dict:
    """List all live sessions for a batch (admin view, optionally includes canceled)."""
    sessions = await live_session_service.list_live_sessions(
        db, batch_id, include_canceled=include_canceled
    )
    return ok([LiveSessionOut.model_validate(s).model_dump() for s in sessions])


@router.get("/admin/live-sessions/{session_id}")
async def get_live_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Fetch a single live session by ID."""
    session = await live_session_service.get_live_session(db, session_id)
    return ok(LiveSessionOut.model_validate(session).model_dump())


@router.patch("/admin/live-sessions/{session_id}")
async def update_live_session(
    session_id: uuid.UUID,
    body: LiveSessionUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Partially update a live session; rescheduling the reminder if starts_at changes."""
    session = await live_session_service.update_live_session(
        db,
        session_id=session_id,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        timezone=body.timezone,
        provider=body.provider,
        join_url=body.join_url,
        recording_url=body.recording_url,
    )
    return ok(LiveSessionOut.model_validate(session).model_dump())


@router.delete("/admin/live-sessions/{session_id}")
async def cancel_live_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Cancel a live session and suppress its pending reminder notification."""
    session = await live_session_service.cancel_live_session(db, session_id)
    return ok(LiveSessionOut.model_validate(session).model_dump())


# ── Student — calendar ─────────────────────────────────────────────────────────

@router.get("/users/me/calendar")
async def get_calendar(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return upcoming live sessions across all of the student's enrolled batches."""
    sessions = await live_session_service.get_calendar_sessions(db, current_user.id)
    items = [
        CalendarSessionOut(
            id=s.id,
            batch_id=s.batch_id,
            batch_title=s.batch.title,
            title=s.title,
            description=s.description,
            starts_at=s.starts_at,
            ends_at=s.ends_at,
            timezone=s.timezone,
            provider=s.provider,
            join_url=s.join_url,
            status=s.status,
        ).model_dump()
        for s in sessions
    ]
    return ok(items)


# ── Attendance ─────────────────────────────────────────────────────────────────

@router.post("/live-sessions/{session_id}/attendance", status_code=201)
async def mark_attendance(
    session_id: uuid.UUID,
    body: AttendanceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
) -> dict:
    """Mark or update attendance for a live session.

    Students may only mark their own attendance.  Admins may mark attendance
    for any batch member by supplying a ``user_id`` in the request body.
    The write is idempotent — calling this endpoint again for the same
    ``(session_id, user_id)`` pair updates the existing record.
    """
    target_user_id = body.user_id if body.user_id is not None else current_user.id
    if target_user_id != current_user.id and current_user.role != Role.ADMIN:
        raise Forbidden()

    record = await attendance_service.mark_attendance(
        db,
        session_id=session_id,
        target_user_id=target_user_id,
        status=body.status,
    )
    return ok(AttendanceOut.model_validate(record).model_dump())


@router.get("/admin/batches/{batch_id}/attendance")
async def get_batch_attendance_report(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    session_id: uuid.UUID | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
) -> dict:
    """Return the attendance report for a batch.

    Optional query parameters:
    * ``?session_id=<uuid>`` — restrict to a single session.
    * ``?user_id=<uuid>`` — restrict to a single student.
    * ``?status=present|absent|late`` — restrict to one attendance status.
    """
    report = await attendance_service.get_batch_attendance_report(
        db,
        batch_id=batch_id,
        filter_session_id=session_id,
        filter_user_id=user_id,
        filter_status=status,
    )
    return ok(report.model_dump())


@router.get("/users/me/calendar.ics")
async def get_calendar_ics(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> Response:
    """Export upcoming live sessions as a valid RFC 5545 iCalendar feed."""
    sessions = await live_session_service.get_calendar_sessions(db, current_user.id)
    data = [
        _SessionData(
            session_id=str(s.id),
            title=s.title,
            description=s.description,
            starts_at=s.starts_at,
            ends_at=s.ends_at,
            join_url=s.join_url,
        )
        for s in sessions
    ]
    ical_content = build_ical(data)
    return Response(
        content=ical_content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=calendar.ics"},
    )
