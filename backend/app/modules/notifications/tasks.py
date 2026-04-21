"""Celery tasks for notification email delivery."""

import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from html import escape

from app.worker.celery_app import celery_app
from app.worker.retry import critical_backoff

logger = logging.getLogger(__name__)
_DELIVERY_ERROR_LIMIT = 1000


def _truncate_error(exc: Exception) -> str:
    """Return a bounded error string safe to store in delivery rows."""
    return f"{type(exc).__name__}: {exc}"[:_DELIVERY_ERROR_LIMIT]


def _render_notification_email(
    notification_type: str,
    title: str,
    body: str,
    target_url: str,
    actor_summary: str,
    frontend_url: str,
) -> tuple[str, str]:
    """Render the subject line and HTML body for a notification email.

    Args:
        notification_type: One of the ``NotificationType`` enum values.
        title: Notification title row (used as email heading).
        body: Notification body preview (used as email paragraph).
        target_url: Relative deep-link path (e.g. ``/lessons/{id}/discussions``).
        actor_summary: Display name of the triggering actor.
        frontend_url: Base URL of the web client (for constructing the CTA link).

    Returns:
        A tuple of ``(subject, html)``.
    """
    full_url = f"{frontend_url.rstrip('/')}/{target_url.lstrip('/')}"

    _SUBJECTS: dict[str, str] = {
        "discussion_reply": f"{actor_summary} replied to your discussion post",
        "mention": f"{actor_summary} mentioned you in a discussion",
        "grade_published": "Your assignment grade has been published",
        "certificate_issued": "Your certificate is ready — XOXO Education",
    }
    subject = " ".join(_SUBJECTS.get(notification_type, title).splitlines())

    _CTA_LABELS: dict[str, str] = {
        "discussion_reply": "View Reply",
        "mention": "View Post",
        "grade_published": "View Grade",
        "certificate_issued": "View Certificate",
    }
    cta_label = _CTA_LABELS.get(notification_type, "View")
    safe_title = escape(title, quote=True)
    safe_body = escape(body, quote=True)
    safe_url = escape(full_url, quote=True)
    safe_cta_label = escape(cta_label, quote=True)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:8px;overflow:hidden;max-width:600px;">
          <tr>
            <td style="background:#1a1a2e;padding:24px 32px;">
              <span style="color:#ffffff;font-size:20px;font-weight:bold;">XOXO Education</span>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;font-size:20px;">{safe_title}</h2>
              <p style="margin:0 0 24px;color:#444444;font-size:15px;
                        line-height:1.6;">{safe_body}</p>
              <a href="{safe_url}"
                 style="display:inline-block;background:#6c63ff;color:#ffffff;
                        text-decoration:none;padding:12px 28px;border-radius:6px;
                        font-size:15px;font-weight:bold;">{safe_cta_label}</a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 24px;border-top:1px solid #eeeeee;">
              <p style="margin:0;color:#999999;font-size:12px;">
                You received this email because you have notifications enabled on XOXO Education.
                Manage your preferences in your account settings.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return subject, html


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=20,
    time_limit=30,
)
def send_notification_email(self, notification_id: str) -> None:
    """Send an email for a persisted notification if the user's preferences allow it.

    Loads the notification and recipient from the database, checks whether
    ``email_enabled`` is set for that notification type in the user's preferences
    (defaulting to ``True`` if no preference row exists), then renders a
    type-specific HTML template and delivers via Resend.

    A Redis guard key ``email_sent:notification:{notification_id}`` is written
    *after* a successful send, providing best-effort dedup on retry.  The guard
    TTL is 7 days — longer than any realistic retry window.

    Retries up to 3 times with critical-queue exponential backoff
    (30 s → 60 s → 120 s) on transient failures.

    Args:
        notification_id: String UUID of the ``Notification`` row to deliver.
    """
    try:
        import redis as sync_redis
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.db.models.notification import (
            Notification,
            NotificationDelivery,
            NotificationPreference,
        )
        from app.db.models.user import User
        from app.modules.notifications.constants import (
            DEFAULT_EMAIL_ENABLED,
            NotificationChannel,
            NotificationDeliveryStatus,
        )
        from app.worker.email import send_email

        guard_key = f"email_sent:notification:{notification_id}"
        rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

        engine = create_engine(settings.DATABASE_URL_SYNC)
        try:
            with Session(engine) as db:
                delivery = db.scalar(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == uuid.UUID(notification_id),
                        NotificationDelivery.channel == NotificationChannel.EMAIL.value,
                    )
                )
                if delivery is None:
                    delivery = NotificationDelivery(
                        notification_id=uuid.UUID(notification_id),
                        channel=NotificationChannel.EMAIL.value,
                        status=NotificationDeliveryStatus.QUEUED.value,
                    )
                    db.add(delivery)
                    db.flush()

                if delivery.status == NotificationDeliveryStatus.SENT.value:
                    return

                guard_exists = False
                with suppress(Exception):
                    guard_exists = bool(rdb.exists(guard_key))
                if guard_exists:
                    delivery.status = NotificationDeliveryStatus.SENT.value
                    delivery.sent_at = delivery.sent_at or datetime.now(UTC)
                    delivery.failed_at = None
                    delivery.last_error = None
                    db.commit()
                    return

                notif = db.scalar(
                    select(Notification).where(Notification.id == uuid.UUID(notification_id))
                )
                if not notif:
                    delivery.status = NotificationDeliveryStatus.FAILED.value
                    delivery.failed_at = datetime.now(UTC)
                    delivery.last_error = "notification not found"
                    db.commit()
                    return

                user = db.get(User, notif.recipient_id)
                if not user or not user.email:
                    delivery.status = NotificationDeliveryStatus.SKIPPED.value
                    delivery.failed_at = None
                    delivery.last_error = "recipient email unavailable"
                    db.commit()
                    return

                pref = db.scalar(
                    select(NotificationPreference).where(
                        NotificationPreference.user_id == notif.recipient_id,
                        NotificationPreference.notification_type == notif.type,
                    )
                )
                email_enabled = pref.email_enabled if pref is not None else DEFAULT_EMAIL_ENABLED
                if not email_enabled:
                    delivery.status = NotificationDeliveryStatus.SKIPPED.value
                    delivery.failed_at = None
                    delivery.last_error = "email preference disabled"
                    db.commit()
                    return

                delivery.status = NotificationDeliveryStatus.QUEUED.value
                delivery.queued_at = delivery.queued_at or datetime.now(UTC)
                delivery.attempt_count = (delivery.attempt_count or 0) + 1
                delivery.failed_at = None
                delivery.last_error = None
                db.commit()

                subject, html = _render_notification_email(
                    notification_type=notif.type,
                    title=notif.title,
                    body=notif.body,
                    target_url=notif.target_url,
                    actor_summary=notif.actor_summary,
                    frontend_url=settings.FRONTEND_URL,
                )
                try:
                    send_email(to=user.email, subject=subject, html=html)
                except Exception as exc:
                    delivery.status = NotificationDeliveryStatus.FAILED.value
                    delivery.failed_at = datetime.now(UTC)
                    delivery.last_error = _truncate_error(exc)
                    db.commit()
                    raise

                delivery.status = NotificationDeliveryStatus.SENT.value
                delivery.sent_at = datetime.now(UTC)
                delivery.failed_at = None
                delivery.last_error = None
                db.commit()

                with suppress(Exception):
                    rdb.set(guard_key, "1", ex=86400 * 7)
        finally:
            engine.dispose()
    except Exception as exc:
        logger.exception(
            "Notification email delivery failed",
            extra={"notification_id": notification_id},
        )
        raise self.retry(exc=exc, countdown=critical_backoff(self.request.retries)) from exc
