"""Celery tasks for live session reminders."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from app.worker.celery_app import celery_app
from app.worker.retry import bulk_backoff

logger = logging.getLogger(__name__)

# Tolerance window: if the session's stored starts_at differs from the
# expected value by more than this many seconds, the task is stale (the
# session was rescheduled after this task was enqueued) and should no-op.
_STARTS_AT_TOLERANCE_SECONDS = 5


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=60,
    time_limit=90,
)
def send_live_session_reminder(
    self,
    session_id: str,
    expected_starts_at_iso: str,
) -> None:
    """Send in-app (and optionally email) reminder notifications to all batch members.

    Idempotency: the task bails out without sending if:
    - The session no longer exists.
    - The session has been canceled.
    - The session's ``starts_at`` differs from ``expected_starts_at_iso``
      by more than ``_STARTS_AT_TOLERANCE_SECONDS`` — this means the session
      was rescheduled and a newer reminder task supersedes this one.

    All notification rows for the batch's enrolled students are created in a
    single database transaction.  Email delivery is enqueued per-recipient via
    ``send_notification_email`` so failures are retried independently.

    Args:
        session_id: String UUID of the ``LiveSession`` to remind about.
        expected_starts_at_iso: ISO-8601 string of the start time this task
            was originally scheduled for.  Used as the idempotency anchor.
    """
    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.db.models.batch import BatchEnrollment
        from app.db.models.live_session import LiveSession
        from app.db.models.notification import Notification
        from app.modules.notifications.constants import NotificationType
        from app.modules.notifications.tasks import send_notification_email

        engine = create_engine(settings.DATABASE_URL_SYNC)
        try:
            with Session(engine) as db:
                session = db.get(LiveSession, uuid.UUID(session_id))
                if not session:
                    logger.info("Reminder skipped: session %s not found", session_id)
                    return
                if session.status != "scheduled":
                    logger.info(
                        "Reminder skipped: session %s status=%s", session_id, session.status
                    )
                    return

                expected_starts_at = datetime.fromisoformat(expected_starts_at_iso)
                if expected_starts_at.tzinfo is None:
                    expected_starts_at = expected_starts_at.replace(tzinfo=UTC)

                actual = session.starts_at
                if actual.tzinfo is None:
                    actual = actual.replace(tzinfo=UTC)

                delta = abs((actual - expected_starts_at).total_seconds())
                if delta > _STARTS_AT_TOLERANCE_SECONDS:
                    logger.info(
                        "Reminder skipped: session %s was rescheduled "
                        "(expected=%s actual=%s delta=%.0fs)",
                        session_id,
                        expected_starts_at_iso,
                        actual.isoformat(),
                        delta,
                    )
                    return

                # Load all batch members
                member_ids = db.execute(
                    select(BatchEnrollment.user_id).where(
                        BatchEnrollment.batch_id == session.batch_id
                    )
                ).scalars().all()

                if not member_ids:
                    return

                # Format a human-friendly start time for the notification body.
                # We keep the display simple (UTC) here; the iCal export and
                # calendar endpoint carry the IANA timezone for rich display.
                starts_label = actual.strftime("%Y-%m-%d %H:%M UTC")
                body = f'"{session.title}" starts at {starts_label}.'

                notifications = [
                    Notification(
                        recipient_id=uid,
                        type=NotificationType.LIVE_SESSION_REMINDER.value,
                        title="Upcoming live session in 1 hour",
                        body=body,
                        actor_summary="XOXO Education",
                        target_url="/users/me/calendar",
                        event_metadata={
                            "session_id": session_id,
                            "batch_id": str(session.batch_id),
                        },
                    )
                    for uid in member_ids
                ]
                db.add_all(notifications)
                db.commit()

                # Enqueue email delivery for each notification
                for notif in notifications:
                    db.refresh(notif)
                    send_notification_email.delay(str(notif.id))

        finally:
            engine.dispose()

    except Exception as exc:
        logger.exception(
            "Live session reminder task failed",
            extra={"session_id": session_id},
        )
        raise self.retry(exc=exc, countdown=bulk_backoff(self.request.retries)) from exc
