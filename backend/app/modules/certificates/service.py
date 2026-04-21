"""Business logic for certificate issuance, listing, verification, and requests."""

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    CertificateAlreadyIssued,
    CertificateNotFound,
    EnrollmentNotFound,
    NotEligibleForCertificate,
)
from app.db.models.certificate import Certificate, CertificateRequest
from app.db.models.enrollment import Enrollment
from app.modules.certificates.schemas import (
    CertificateOut,
    CertificateRequestOut,
    VerifyResponse,
)


async def check_and_issue(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> CertificateOut | None:
    """Issue a certificate if the student has completed the course.

    Called automatically after a lesson is marked complete.  If the enrollment
    is not yet ``"completed"`` or a certificate already exists, returns ``None``
    without raising.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the course.

    Returns:
        The newly created ``CertificateOut`` if issued, or ``None`` if the
        student is not yet eligible.
    """
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.status == "completed",
        )
    )
    if not enrollment:
        return None

    existing = await db.scalar(
        select(Certificate).where(
            Certificate.user_id == user_id,
            Certificate.course_id == course_id,
        )
    )
    if existing:
        return None

    cert = Certificate(
        user_id=user_id,
        course_id=course_id,
        verification_token=secrets.token_urlsafe(32),
    )
    db.add(cert)
    await db.flush()

    from app.modules.notifications import service as notification_service

    cert_notif = notification_service.build_certificate_issued_notification(
        recipient_id=user_id,
        certificate_id=cert.id,
        course_id=course_id,
    )
    db.add(cert_notif)
    await db.flush()  # populate cert_notif.id + created_at before commit
    cert_notif_id = cert_notif.id
    cert_notif_type = cert_notif.type
    cert_notif_out = notification_service.notification_to_out(cert_notif)

    await db.commit()
    await db.refresh(cert)

    from app.modules.certificates.tasks import generate_certificate_pdf
    generate_certificate_pdf.delay(str(cert.id))

    await notification_service.dispatch_notification_delivery(
        db,
        notification_id=cert_notif_id,
        recipient_id=user_id,
        notification_type=cert_notif_type,
        notification_out=cert_notif_out,
    )

    return CertificateOut.model_validate(cert)


async def generate(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> CertificateOut:
    """Manually trigger certificate generation for a completed course.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.
        course_id: UUID of the course.

    Returns:
        The ``CertificateOut`` for the newly or previously issued certificate.

    Raises:
        EnrollmentNotFound: If no completed enrollment exists for this pair.
        CertificateAlreadyIssued: If a certificate has already been issued.
        NotEligibleForCertificate: If the course enrollment is not completed.
    """
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
        )
    )
    if not enrollment:
        raise EnrollmentNotFound()

    if enrollment.status != "completed":
        raise NotEligibleForCertificate()

    existing = await db.scalar(
        select(Certificate).where(
            Certificate.user_id == user_id,
            Certificate.course_id == course_id,
        )
    )
    if existing:
        raise CertificateAlreadyIssued()

    cert = Certificate(
        user_id=user_id,
        course_id=course_id,
        verification_token=secrets.token_urlsafe(32),
    )
    db.add(cert)
    await db.flush()

    from app.modules.notifications import service as notification_service

    cert_notif = notification_service.build_certificate_issued_notification(
        recipient_id=user_id,
        certificate_id=cert.id,
        course_id=course_id,
    )
    db.add(cert_notif)
    await db.flush()  # populate cert_notif.id + created_at before commit
    cert_notif_id = cert_notif.id
    cert_notif_type = cert_notif.type
    cert_notif_out = notification_service.notification_to_out(cert_notif)

    await db.commit()
    await db.refresh(cert)

    from app.modules.certificates.tasks import generate_certificate_pdf
    generate_certificate_pdf.delay(str(cert.id))

    await notification_service.dispatch_notification_delivery(
        db,
        notification_id=cert_notif_id,
        recipient_id=user_id,
        notification_type=cert_notif_type,
        notification_out=cert_notif_out,
    )

    return CertificateOut.model_validate(cert)


async def list_certificates(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CertificateOut]:
    """Return all certificates earned by a student.

    Args:
        db: Async database session.
        user_id: UUID of the student.

    Returns:
        List of ``CertificateOut`` schemas ordered by issue date descending.
    """
    rows = await db.scalars(
        select(Certificate)
        .where(Certificate.user_id == user_id)
        .order_by(Certificate.issued_at.desc())
    )
    return [CertificateOut.model_validate(c) for c in rows]


async def verify(db: AsyncSession, token: str) -> VerifyResponse:
    """Look up a certificate by its public verification token.

    Args:
        db: Async database session.
        token: The ``verification_token`` from the certificate URL.

    Returns:
        A ``VerifyResponse`` with student and course details.

    Raises:
        CertificateNotFound: If no certificate matches the token.
    """
    cert = await db.scalar(
        select(Certificate)
        .where(Certificate.verification_token == token)
        .options(selectinload(Certificate.course))
    )
    if not cert:
        raise CertificateNotFound()

    from app.db.models.user import User
    user = await db.get(User, cert.user_id)

    student_name = (user.display_name if user and user.display_name else None) or (
        user.email if user else "Student"
    )
    instructor_name = cert.course.display_instructor_name if cert.course else None

    return VerifyResponse(
        verification_token=cert.verification_token,
        student_name=student_name,
        course_title=cert.course.title if cert.course else "",
        issued_at=cert.issued_at,
        instructor_name=instructor_name,
        pdf_url=cert.pdf_url,
    )


async def create_request(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> CertificateRequestOut:
    """Submit a manual certificate review request.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the course.

    Returns:
        The created ``CertificateRequestOut`` with status ``"pending"``.
    """
    req = CertificateRequest(
        user_id=user_id,
        course_id=course_id,
        status="pending",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return CertificateRequestOut.model_validate(req)
