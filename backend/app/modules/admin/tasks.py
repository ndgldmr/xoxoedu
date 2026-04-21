"""Celery tasks for admin operations — announcement email dispatch and delivery."""

from app.worker.celery_app import celery_app
from app.worker.retry import bulk_backoff

_BATCH_SIZE = 50  # recipients per leaf task


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=30,
    time_limit=60,
)
def send_announcement_emails(
    self,
    announcement_id: str,
    recipient_emails: list[str],
    title: str,
    body: str,
) -> None:
    """Dispatch an announcement by fanning out into fixed-size batch tasks.

    Splits ``recipient_emails`` into batches of ``_BATCH_SIZE`` and enqueues
    one ``send_announcement_email_batch`` task per batch on the ``bulk_email``
    queue.  Keeping the dispatch task lightweight means it can safely retry
    (re-enqueueing all batches) without risk of duplicate delivery — each leaf
    task has a per-recipient Redis guard.

    Retries up to 3 times with exponential backoff (60 s → 120 s → 240 s) on
    broker publish failures.

    Args:
        announcement_id: String UUID of the source ``Announcement`` row.
        recipient_emails: Full list of email addresses to notify.
        title: Subject line for the email.
        body: Plain-text body of the announcement.
    """
    try:
        for i in range(0, len(recipient_emails), _BATCH_SIZE):
            batch = recipient_emails[i : i + _BATCH_SIZE]
            send_announcement_email_batch.delay(announcement_id, batch, title, body)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=bulk_backoff(self.request.retries)) from exc


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=90,
    time_limit=120,
)
def send_announcement_email_batch(
    self,
    announcement_id: str,
    batch_emails: list[str],
    title: str,
    body: str,
) -> None:
    """Send announcement emails to one batch of recipients.

    Each recipient has a Redis guard key
    ``announcement_sent:{announcement_id}:{email}`` (7-day TTL) written
    *after* a successful ``send_email`` call.  This eliminates duplicates from
    the most common case — a single worker retrying a failed batch — without
    permanently blocking an address if the send itself fails.  Concurrent
    execution by two workers (possible under ``task_acks_late`` redelivery)
    is not prevented and may produce a duplicate for recipients processed in
    the window between the two workers' guard checks.  This risk is accepted:
    one extra announcement email is less harmful than a lost one.

    Retries up to 3 times with exponential backoff (60 s → 120 s → 240 s).

    Args:
        announcement_id: String UUID of the source ``Announcement`` row (for
            the guard key and logging).
        batch_emails: Slice of recipient email addresses for this batch.
        title: Subject line for the email.
        body: Plain-text body of the announcement.
    """
    try:
        import redis as sync_redis

        from app.config import settings
        from app.worker.email import send_email

        rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

        html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h2 style="color: #1a1a2e;">{title}</h2>
  <div style="color: #333; line-height: 1.6;">{body}</div>
  <hr style="margin-top: 32px; border: none; border-top: 1px solid #eee;" />
  <p style="font-size: 12px; color: #aaa;">XOXO Education &mdash; {announcement_id}</p>
</body>
</html>"""

        for email in batch_emails:
            guard_key = f"announcement_sent:{announcement_id}:{email}"
            if rdb.exists(guard_key):
                continue
            send_email(to=email, subject=title, html=html_body)
            rdb.set(guard_key, "1", ex=7 * 86400)  # 7-day TTL covers any retry window

    except Exception as exc:
        raise self.retry(exc=exc, countdown=bulk_backoff(self.request.retries)) from exc
