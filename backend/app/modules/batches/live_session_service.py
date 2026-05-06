"""Business logic for live session CRUD and student calendar retrieval."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BatchArchived,
    BatchNotFound,
    LiveSessionCanceled,
    LiveSessionNotFound,
)
from app.db.models.batch import Batch, BatchEnrollment
from app.db.models.live_session import LiveSession

logger = logging.getLogger(__name__)

_REMINDER_LEAD_SECONDS = 3600  # 1 hour before session start


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _get_session(db: AsyncSession, session_id: uuid.UUID) -> LiveSession:
    """Fetch a live session by primary key or raise ``LiveSessionNotFound``."""
    row = await db.get(LiveSession, session_id)
    if not row:
        raise LiveSessionNotFound()
    return row


def _schedule_reminder(session_id: uuid.UUID, starts_at: datetime) -> str | None:
    """Enqueue a live-session reminder task and return its Celery task ID.

    The reminder fires ``_REMINDER_LEAD_SECONDS`` before the session start.
    Returns ``None`` if the reminder time is already in the past (session
    starts within the next hour or has already started).

    The ``expected_starts_at_iso`` argument passed to the task is the
    idempotency anchor: if the session is later rescheduled, the old task's
    anchor will no longer match the DB row and the task will bail out without
    sending notifications.
    """
    from app.modules.batches.tasks import send_live_session_reminder

    eta = starts_at - timedelta(seconds=_REMINDER_LEAD_SECONDS)
    now = datetime.now(UTC)
    if eta <= now:
        return None

    result = send_live_session_reminder.apply_async(
        args=[str(session_id), starts_at.isoformat()],
        eta=eta,
    )
    return result.id  # type: ignore[no-any-return]


def _revoke_reminder(task_id: str | None) -> None:
    """Best-effort revoke of a previously scheduled reminder task.

    With RabbitMQ, ``revoke()`` prevents execution if the worker has not yet
    started the task.  The task's own idempotency check handles the case where
    the revoke signal arrives too late.
    """
    if not task_id:
        return
    try:
        from app.worker.celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=False)
    except Exception:
        logger.warning("Failed to revoke reminder task %s", task_id)


# ── Live session CRUD ──────────────────────────────────────────────────────────

async def create_live_session(
    db: AsyncSession,
    batch_id: uuid.UUID,
    title: str,
    description: str | None,
    starts_at: datetime,
    ends_at: datetime,
    timezone: str,
    provider: str | None,
    join_url: str | None,
    recording_url: str | None,
) -> LiveSession:
    """Create a new live session under a batch and schedule a reminder.

    Args:
        db: Async database session.
        batch_id: UUID of the parent batch.
        title: Short session label.
        description: Optional longer description.
        starts_at: UTC start datetime.
        ends_at: UTC end datetime.
        timezone: IANA timezone name for display.
        provider: Optional meeting platform label.
        join_url: Protected join link; only shared with authenticated students.
        recording_url: Optional post-session recording link.

    Returns:
        The newly created ``LiveSession`` ORM instance.

    Raises:
        BatchNotFound: If the batch does not exist.
        BatchArchived: If the batch is archived.
    """
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise BatchNotFound()
    if batch.status == "archived":
        raise BatchArchived()

    session = LiveSession(
        batch_id=batch_id,
        title=title,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        timezone=timezone,
        provider=provider,
        join_url=join_url,
        recording_url=recording_url,
        status="scheduled",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    task_id = _schedule_reminder(session.id, starts_at)
    if task_id:
        session.reminder_task_id = task_id
        await db.commit()

    return session


async def get_live_session(db: AsyncSession, session_id: uuid.UUID) -> LiveSession:
    """Return a live session by primary key.

    Raises:
        LiveSessionNotFound: If no session with that ID exists.
    """
    return await _get_session(db, session_id)


async def list_live_sessions(
    db: AsyncSession,
    batch_id: uuid.UUID,
    include_canceled: bool = False,
) -> list[LiveSession]:
    """Return all live sessions for a batch, ordered by start time.

    Args:
        db: Async database session.
        batch_id: UUID of the parent batch.
        include_canceled: When ``True``, canceled sessions are included.
            Admins pass ``True``; the default ``False`` is safe for students.

    Raises:
        BatchNotFound: If the batch does not exist.
    """
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise BatchNotFound()

    stmt = select(LiveSession).where(LiveSession.batch_id == batch_id)
    if not include_canceled:
        stmt = stmt.where(LiveSession.status == "scheduled")
    stmt = stmt.order_by(LiveSession.starts_at.asc())
    rows = await db.scalars(stmt)
    return list(rows.all())


async def update_live_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    title: str | None,
    description: str | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
    timezone: str | None,
    provider: str | None,
    join_url: str | None,
    recording_url: str | None,
) -> LiveSession:
    """Apply a partial update to a live session.

    If ``starts_at`` changes, the existing reminder task is revoked (best-effort)
    and a new one is scheduled at the updated time.

    Raises:
        LiveSessionNotFound: If the session does not exist.
        LiveSessionCanceled: If the session has already been canceled.
    """
    session = await _get_session(db, session_id)
    if session.status == "canceled":
        raise LiveSessionCanceled()

    starts_at_changed = starts_at is not None and starts_at != session.starts_at

    if title is not None:
        session.title = title
    if description is not None:
        session.description = description
    if starts_at is not None:
        session.starts_at = starts_at
    if ends_at is not None:
        session.ends_at = ends_at
    if timezone is not None:
        session.timezone = timezone
    if provider is not None:
        session.provider = provider
    if join_url is not None:
        session.join_url = join_url
    if recording_url is not None:
        session.recording_url = recording_url

    if starts_at_changed:
        _revoke_reminder(session.reminder_task_id)
        new_task_id = _schedule_reminder(session.id, session.starts_at)
        session.reminder_task_id = new_task_id

    await db.commit()
    await db.refresh(session)
    return session


async def cancel_live_session(db: AsyncSession, session_id: uuid.UUID) -> LiveSession:
    """Cancel a live session and suppress its pending reminder.

    Raises:
        LiveSessionNotFound: If the session does not exist.
        LiveSessionCanceled: If the session is already canceled.
    """
    session = await _get_session(db, session_id)
    if session.status == "canceled":
        raise LiveSessionCanceled()

    _revoke_reminder(session.reminder_task_id)
    session.status = "canceled"
    session.reminder_task_id = None
    await db.commit()
    await db.refresh(session)
    return session


# ── Student calendar ───────────────────────────────────────────────────────────

async def get_calendar_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[LiveSession]:
    """Return upcoming scheduled sessions across the current user's batches.

    Only sessions from batches the user is enrolled in are returned.
    Canceled sessions and sessions in the past are excluded.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.

    Returns:
        List of ``LiveSession`` rows ordered by ``starts_at`` ascending,
        each with its ``batch`` relationship loaded.
    """
    now = datetime.now(UTC)
    stmt = (
        select(LiveSession)
        .join(Batch, LiveSession.batch_id == Batch.id)
        .join(
            BatchEnrollment,
            (BatchEnrollment.batch_id == Batch.id)
            & (BatchEnrollment.user_id == user_id),
        )
        .where(
            LiveSession.status == "scheduled",
            LiveSession.starts_at > now,
        )
        .options(selectinload(LiveSession.batch))
        .order_by(LiveSession.starts_at.asc())
    )
    rows = await db.scalars(stmt)
    return list(rows.all())
