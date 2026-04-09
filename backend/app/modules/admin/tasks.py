"""Celery tasks for admin operations — currently announcement email dispatch."""

from app.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[misc]
def send_announcement_emails(
    self,
    announcement_id: str,
    recipient_emails: list[str],
    title: str,
    body: str,
) -> None:
    """Send announcement emails to a list of recipients.

    Each recipient receives a separate email so that delivery failures for one
    address do not block the rest.  The task retries up to 3 times on any
    unhandled exception.

    Args:
        announcement_id: String UUID of the source ``Announcement`` row (for logging).
        recipient_emails: List of email addresses to notify.
        title: Subject line for the email.
        body: Plain-text body of the announcement (displayed inside a minimal HTML wrapper).
    """
    try:
        from app.worker.email import send_email

        html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h2 style="color: #1a1a2e;">{title}</h2>
  <div style="color: #333; line-height: 1.6;">{body}</div>
  <hr style="margin-top: 32px; border: none; border-top: 1px solid #eee;" />
  <p style="font-size: 12px; color: #aaa;">XOXO Education &mdash; {announcement_id}</p>
</body>
</html>"""

        for email in recipient_emails:
            send_email(to=email, subject=title, html=html_body)

    except Exception as exc:
        raise self.retry(exc=exc) from exc
