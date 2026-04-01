"""Celery tasks for sending transactional authentication emails via Resend."""

from app.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[misc]
def send_verification_email(self, email: str, token: str) -> None:
    """Send the email-address verification email with a signed 24-hour link.

    Retries up to 3 times with a 60-second delay on transient delivery failures.

    Args:
        email: Recipient email address.
        token: Signed verification token produced by ``create_email_token``.
    """
    from app.config import settings
    from app.worker.email import send_email

    verify_url = f"{settings.FRONTEND_URL}/verify-email/{token}"
    html = (
        f"<p>Thanks for signing up! Click the link below to verify your email address.</p>"
        f"<p><a href='{verify_url}'>Verify your email</a></p>"
        f"<p>This link expires in 24 hours.</p>"
    )
    try:
        send_email(to=email, subject="Verify your xoxo Education account", html=html)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[misc]
def send_password_reset_email(self, email: str, token: str) -> None:
    """Send the password-reset email with a signed 1-hour link.

    Retries up to 3 times with a 60-second delay on transient delivery failures.

    Args:
        email: Recipient email address.
        token: Signed reset token produced by ``create_email_token``.
    """
    from app.config import settings
    from app.worker.email import send_email

    reset_url = f"{settings.FRONTEND_URL}/reset-password/{token}"
    html = (
        f"<p>We received a request to reset your password.</p>"
        f"<p><a href='{reset_url}'>Reset your password</a></p>"
        "<p>This link expires in 1 hour. If you didn't request this, ignore it.</p>"
    )
    try:
        send_email(to=email, subject="Reset your xoxo Education password", html=html)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
