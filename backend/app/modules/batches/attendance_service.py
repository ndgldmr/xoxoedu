"""Business logic for live-session attendance marking and batch reporting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BatchNotFound,
    LiveSessionNotFound,
    NotABatchMember,
)
from app.db.models.batch import Batch, BatchEnrollment
from app.db.models.live_session import LiveSession
from app.db.models.session_attendance import SessionAttendance
from app.modules.batches.attendance_schemas import (
    BatchAttendanceReportOut,
    SessionSummaryOut,
    StudentSummaryOut,
)


def _attendance_rate(attended: int, total: int) -> float:
    """Return ``attended / total`` rounded to 4 decimal places, or ``0.0`` if total is zero.

    Args:
        attended: Count of attended records (present + late).
        total: Denominator (total sessions or total members).

    Returns:
        Float in the range [0.0, 1.0].
    """
    if total == 0:
        return 0.0
    return round(attended / total, 4)


async def mark_attendance(
    db: AsyncSession,
    session_id: uuid.UUID,
    target_user_id: uuid.UUID,
    status: str,
) -> SessionAttendance:
    """Create or update an attendance record for a student at a live session.

    The write is idempotent: calling this function multiple times with the
    same ``(session_id, target_user_id)`` pair updates the existing row's
    ``status`` and ``updated_at`` rather than inserting a duplicate.

    Attendance writes are permitted regardless of the session's current
    ``status`` (including canceled sessions) and regardless of whether the
    session time has passed, so that staff can backfill missing records.

    Args:
        db: Async database session.
        session_id: UUID of the live session.
        target_user_id: UUID of the student whose attendance is being recorded.
        status: Attendance status — ``"present"``, ``"absent"``, or ``"late"``.

    Returns:
        The upserted ``SessionAttendance`` ORM row.

    Raises:
        LiveSessionNotFound: If no live session with ``session_id`` exists.
        NotABatchMember: If ``target_user_id`` is not enrolled in the batch
            that owns the session.
    """
    # 1. Fetch the live session to resolve the batch_id.
    live_session = await db.get(LiveSession, session_id)
    if not live_session:
        raise LiveSessionNotFound()

    # 2. Verify the target user is a member of the session's batch.
    be = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.batch_id == live_session.batch_id,
            BatchEnrollment.user_id == target_user_id,
        )
    )
    if not be:
        raise NotABatchMember()

    # 3. Upsert the attendance record.
    stmt = (
        pg_insert(SessionAttendance)
        .values(
            id=uuid.uuid4(),
            session_id=session_id,
            user_id=target_user_id,
            status=status,
        )
        .on_conflict_do_update(
            constraint="uq_session_attendance_session_user",
            set_={"status": status, "updated_at": datetime.now(UTC)},
        )
    )
    await db.execute(stmt)
    await db.commit()

    # 4. Fetch and return the committed row.
    record = await db.scalar(
        select(SessionAttendance).where(
            SessionAttendance.session_id == session_id,
            SessionAttendance.user_id == target_user_id,
        )
    )
    return record  # type: ignore[return-value]


async def get_batch_attendance_report(
    db: AsyncSession,
    batch_id: uuid.UUID,
    filter_session_id: uuid.UUID | None = None,
    filter_user_id: uuid.UUID | None = None,
    filter_status: str | None = None,
) -> BatchAttendanceReportOut:
    """Build a complete attendance report for a batch.

    The report contains three layers:
    * **session_summaries** — per-session totals (present / absent / late /
      unmarked) ordered by start time.
    * **student_summaries** — per-student breakdowns with a session →
      status mapping and aggregate counts, ordered by email.
    * **Batch-level totals** — overall attendance rate across all
      (session, member) pairs.

    Optional filters narrow the data set:
    * ``filter_session_id`` — include only the specified session.
    * ``filter_user_id`` — include only the specified student.
    * ``filter_status`` — include only attendance records with the given
      status.  Counts in summaries reflect the filtered records; records of
      other statuses are excluded from ``attendance`` dicts and totals.

    Args:
        db: Async database session.
        batch_id: UUID of the batch to report on.
        filter_session_id: Restrict to a single session (optional).
        filter_user_id: Restrict to a single student (optional).
        filter_status: Restrict to one attendance status (optional).

    Returns:
        A fully populated ``BatchAttendanceReportOut`` instance.

    Raises:
        BatchNotFound: If no batch with ``batch_id`` exists.
    """
    # 1. Verify the batch exists.
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise BatchNotFound()

    # 2. Fetch sessions (optionally scoped to a single session).
    sessions_stmt = (
        select(LiveSession)
        .where(LiveSession.batch_id == batch_id)
        .order_by(LiveSession.starts_at.asc())
    )
    if filter_session_id is not None:
        sessions_stmt = sessions_stmt.where(LiveSession.id == filter_session_id)
    sessions = list((await db.scalars(sessions_stmt)).all())
    session_ids = [s.id for s in sessions]

    # 3. Fetch batch members with user info (optionally scoped to one user).
    members_stmt = (
        select(BatchEnrollment)
        .where(BatchEnrollment.batch_id == batch_id)
        .options(selectinload(BatchEnrollment.user))
        .order_by(BatchEnrollment.user_id)  # stable ordering before email sort
    )
    if filter_user_id is not None:
        members_stmt = members_stmt.where(BatchEnrollment.user_id == filter_user_id)
    members = list((await db.scalars(members_stmt)).all())
    member_user_ids = [m.user_id for m in members]

    # 4. Fetch attendance records for the resolved session × member set.
    attendance_records: list[SessionAttendance] = []
    if session_ids and member_user_ids:
        att_stmt = select(SessionAttendance).where(
            SessionAttendance.session_id.in_(session_ids),
            SessionAttendance.user_id.in_(member_user_ids),
        )
        if filter_status is not None:
            att_stmt = att_stmt.where(SessionAttendance.status == filter_status)
        attendance_records = list((await db.scalars(att_stmt)).all())

    total_sessions = len(sessions)
    total_members = len(members)

    # 5. Build pivot: {session_id: {user_id: status}}
    att_map: dict[uuid.UUID, dict[uuid.UUID, str]] = {s.id: {} for s in sessions}
    for rec in attendance_records:
        att_map[rec.session_id][rec.user_id] = rec.status

    # 6. Session summaries.
    session_summaries: list[SessionSummaryOut] = []
    for s in sessions:
        sess_att = att_map[s.id]
        present = sum(1 for st in sess_att.values() if st == "present")
        absent = sum(1 for st in sess_att.values() if st == "absent")
        late = sum(1 for st in sess_att.values() if st == "late")
        # "unmarked" = members who have no matching record for this session
        # (when a status filter is active, members with a non-matching record
        # are also counted as unmarked from the filter's perspective).
        unmarked = total_members - len(sess_att)
        session_summaries.append(
            SessionSummaryOut(
                session_id=s.id,
                title=s.title,
                starts_at=s.starts_at,
                present=present,
                absent=absent,
                late=late,
                unmarked=max(unmarked, 0),
                total_members=total_members,
                attendance_rate=_attendance_rate(present + late, total_members),
            )
        )

    # 7. Student summaries (sorted by email for stable output).
    members.sort(key=lambda m: m.user.email)
    student_summaries: list[StudentSummaryOut] = []
    for m in members:
        user = m.user
        per_session: dict[str, str] = {}
        for s in sessions:
            status = att_map[s.id].get(user.id)
            if status is not None:
                per_session[str(s.id)] = status

        present_count = sum(1 for st in per_session.values() if st == "present")
        absent_count = sum(1 for st in per_session.values() if st == "absent")
        late_count = sum(1 for st in per_session.values() if st == "late")
        student_summaries.append(
            StudentSummaryOut(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                attendance=per_session,
                present_count=present_count,
                absent_count=absent_count,
                late_count=late_count,
                attendance_rate=_attendance_rate(
                    present_count + late_count, total_sessions
                ),
            )
        )

    # 8. Overall rate: (total present + late) / (total_sessions × total_members).
    total_attended = sum(
        1 for rec in attendance_records if rec.status in ("present", "late")
    )
    total_pairs = total_sessions * total_members
    overall_rate = _attendance_rate(total_attended, total_pairs)

    return BatchAttendanceReportOut(
        batch_id=batch_id,
        total_sessions=total_sessions,
        total_members=total_members,
        overall_attendance_rate=overall_rate,
        session_summaries=session_summaries,
        student_summaries=student_summaries,
    )
