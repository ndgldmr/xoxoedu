"""Celery tasks for certificate PDF generation."""

import uuid

from app.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[misc]
def generate_certificate_pdf(self, certificate_id: str) -> None:
    """Generate a certificate PDF and upload it to R2.

    Loads the certificate, student, and course from the database using a
    synchronous session (Celery workers run outside of asyncio), renders an
    HTML template, converts it to PDF via WeasyPrint, and stores the result
    in R2 under ``certificates/<certificate_id>.pdf``.

    Args:
        certificate_id: String UUID of the certificate row to process.
    """
    try:
        import weasyprint
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.core.storage import get_public_url, get_r2_client
        from app.db.models.certificate import Certificate
        from app.db.models.user import User, UserProfile

        engine = create_engine(settings.DATABASE_URL_SYNC)
        with Session(engine) as db:
            cert = db.get(Certificate, uuid.UUID(certificate_id))
            if not cert:
                return

            user = db.get(User, cert.user_id)
            from sqlalchemy import select
            profile = db.scalar(
                select(UserProfile).where(UserProfile.user_id == cert.user_id)
            )
            from app.db.models.course import Course
            course = db.get(Course, cert.course_id)

            if not cert or not user or not course:
                return

            student_name = (
                (profile.display_name if profile and profile.display_name else None)
                or user.email
            )
            instructor_name = course.display_instructor_name or "XOXO Education"
            issued_date = cert.issued_at.strftime("%B %d, %Y")

            html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4 landscape; margin: 2cm; }}
  body {{
    font-family: Georgia, serif;
    text-align: center;
    color: #1a1a2e;
    background: #fff;
  }}
  .border {{
    border: 8px double #c9a84c;
    padding: 40px;
    height: calc(100vh - 4cm - 80px);
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }}
  h1 {{ font-size: 48px; margin: 0 0 8px; color: #c9a84c; letter-spacing: 4px; }}
  .subtitle {{ font-size: 18px; color: #555; margin-bottom: 32px; }}
  .student {{
    font-size: 36px; font-style: italic; margin: 16px 0;
    border-bottom: 2px solid #c9a84c; padding-bottom: 8px;
  }}
  .course {{ font-size: 22px; font-weight: bold; margin: 12px 0 24px; }}
  .meta {{ font-size: 14px; color: #777; margin-top: 32px; }}
  .token {{ font-size: 11px; color: #aaa; margin-top: 8px; }}
</style>
</head>
<body>
<div class="border">
  <h1>CERTIFICATE</h1>
  <p class="subtitle">of Completion</p>
  <p>This certifies that</p>
  <p class="student">{student_name}</p>
  <p>has successfully completed the course</p>
  <p class="course">{course.title}</p>
  <p>Issued on {issued_date} · Instructor: {instructor_name}</p>
  <p class="token">Verification: {cert.verification_token}</p>
</div>
</body>
</html>"""

            pdf_bytes = weasyprint.HTML(string=html).write_pdf()

            key = f"certificates/{certificate_id}.pdf"
            client = get_r2_client()
            client.put_object(  # type: ignore[union-attr]
                Bucket=settings.R2_BUCKET,
                Key=key,
                Body=pdf_bytes,
                ContentType="application/pdf",
            )

            cert.pdf_url = get_public_url(key)
            db.commit()

    except Exception as exc:
        raise self.retry(exc=exc) from exc
