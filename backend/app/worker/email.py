"""Resend email delivery helper used by Celery tasks."""

import resend

from app.config import settings


def send_email(to: str, subject: str, html: str) -> None:
    """Send an HTML transactional email via the Resend API.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        html: Full HTML body of the email.
    """
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(
        {
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        }
    )
