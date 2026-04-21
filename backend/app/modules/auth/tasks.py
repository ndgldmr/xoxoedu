"""Celery tasks for sending transactional authentication emails via Resend."""

from app.worker.celery_app import celery_app
from app.worker.retry import critical_backoff


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=5,
    soft_time_limit=20,
    time_limit=30,
)
def send_verification_email(self, email: str, token: str) -> None:
    """Send the email-address verification email with a signed 24-hour link.

    Retries up to 5 times with exponential backoff (30 s → 60 s → 120 s →
    240 s → 480 s) on transient delivery failures, including Redis downtime.
    The entire function body is wrapped in a single try/except so that Redis
    connectivity errors go through the retry path rather than failing immediately.

    A Redis key (``email_sent:verify:{token}``) provides best-effort dedup:
    the key is written *after* a successful send, so a single worker retrying
    after a transient failure will not resend.  Concurrent execution by two
    workers — possible under ``task_acks_late`` redelivery — is not prevented
    and may still produce a duplicate.  This is acceptable because the user can
    ignore a second verification email and the token is identical each time.

    Args:
        email: Recipient email address.
        token: Signed verification token produced by ``create_email_token``.
    """
    try:
        import redis as sync_redis

        from app.config import settings
        from app.worker.email import send_email

        guard_key = f"email_sent:verify:{token}"
        rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

        if rdb.exists(guard_key):
            return

        verify_url = f"{settings.FRONTEND_URL}/verify-email/{token}"
        html = (
            f"<p>Thanks for signing up! Click the link below to verify your email address.</p>"
            f"<p><a href='{verify_url}'>Verify your email</a></p>"
            f"<p>This link expires in 24 hours.</p>"
        )
        send_email(to=email, subject="Verify your XOXO Education account", html=html)
        rdb.set(guard_key, "1", ex=86400)  # TTL matches 24-hour token expiry
    except Exception as exc:
        raise self.retry(exc=exc, countdown=critical_backoff(self.request.retries)) from exc


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=5,
    soft_time_limit=20,
    time_limit=30,
)
def send_password_reset_email(self, email: str, token: str) -> None:
    """Send the password-reset email with a signed 1-hour link.

    Retries up to 5 times with exponential backoff (30 s → 60 s → 120 s →
    240 s → 480 s) on transient delivery failures, including Redis downtime.
    The entire function body is wrapped in a single try/except so that Redis
    connectivity errors go through the retry path rather than failing immediately.

    A Redis key (``email_sent:reset:{token}``) provides best-effort dedup:
    the key is written *after* a successful send, so a single worker retrying
    after a transient failure will not resend.  Concurrent execution by two
    workers — possible under ``task_acks_late`` redelivery — is not prevented
    and may produce a duplicate.  This is acceptable because reset tokens expire
    in 1 hour and the user can ignore a second email.

    Args:
        email: Recipient email address.
        token: Signed reset token produced by ``create_email_token``.
    """
    try:
        import redis as sync_redis

        from app.config import settings
        from app.worker.email import send_email

        guard_key = f"email_sent:reset:{token}"
        rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

        if rdb.exists(guard_key):
            return

        reset_url = f"{settings.FRONTEND_URL}/reset-password/{token}"
        html = (
            f"<p>We received a request to reset your password.</p>"
            f"<p><a href='{reset_url}'>Reset your password</a></p>"
            "<p>This link expires in 1 hour. If you didn't request this, ignore it.</p>"
        )
        send_email(to=email, subject="Reset your XOXO Education password", html=html)
        rdb.set(guard_key, "1", ex=3600)  # TTL matches 1-hour token expiry
    except Exception as exc:
        raise self.retry(exc=exc, countdown=critical_backoff(self.request.retries)) from exc
