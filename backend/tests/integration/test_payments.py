"""Integration tests for Stripe webhook processing and payment history."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment
from app.db.models.payment import Payment
from app.db.models.user import User


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
    local, domain = email.split("@")
    email = f"{local}_{uuid.uuid4().hex[:8]}@{domain}"
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass"),
        role=role,
        email_verified=True,
        display_name="Test User",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_paid_course(db: AsyncSession, created_by: uuid.UUID) -> Course:
    course = Course(
        slug=f"paid-course-{uuid.uuid4().hex[:8]}",
        title="Paid Course",
        level="beginner",
        language="en",
        price_cents=4999,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.flush()
    chapter = Chapter(course_id=course.id, title="Ch 1", position=1)
    db.add(chapter)
    await db.flush()
    db.add(Lesson(chapter_id=chapter.id, title="L1", position=1, type="video", is_free_preview=False))
    await db.commit()
    await db.refresh(course)
    return course


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_checkout_completed_creates_enrollment(
    client: AsyncClient, db: AsyncSession
) -> None:
    """checkout.session.completed webhook creates enrollment and sets payment completed."""
    instructor, _ = await _make_user(db, f"instr-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_paid_course(db, instructor.id)

    payment = Payment(
        user_id=student.id,
        course_id=course.id,
        amount_cents=4999,
        status="pending",
        provider_payment_id=f"cs_test_{uuid.uuid4().hex}",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    session_id = payment.provider_payment_id
    payload = json.dumps({
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "metadata": {
                    "payment_id": str(payment.id),
                    "user_id": str(student.id),
                    "course_id": str(course.id),
                },
            }
        },
    }).encode()

    mock_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "metadata": {
                    "payment_id": str(payment.id),
                    "user_id": str(student.id),
                    "course_id": str(course.id),
                },
            }
        },
    }
    with patch("stripe.Webhook.construct_event", return_value=mock_event):
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=payload,
            headers={"stripe-signature": "t=123,v1=abc"},
        )

    assert resp.status_code == 200

    await db.refresh(payment)
    assert payment.status == "completed"

    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == student.id,
            Enrollment.course_id == course.id,
        )
    )
    assert enrollment is not None
    assert enrollment.status == "active"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A bad Stripe signature is rejected with 400."""
    import stripe

    with patch("stripe.Webhook.construct_event", side_effect=stripe.error.SignatureVerificationError("bad sig", "hdr")):
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=b"{}",
            headers={"stripe-signature": "bad"},
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_refund_updates_enrollment_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    """charge.refunded webhook sets payment and enrollment to refunded."""
    instructor, _ = await _make_user(db, f"instr2-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu2-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_paid_course(db, instructor.id)

    payment_intent_id = f"pi_{uuid.uuid4().hex}"
    payment = Payment(
        user_id=student.id,
        course_id=course.id,
        amount_cents=4999,
        status="completed",
        provider_payment_id=payment_intent_id,
    )
    db.add(payment)
    enrollment = Enrollment(
        user_id=student.id,
        course_id=course.id,
        status="active",
        payment_id=str(payment.id) if payment.id else None,
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(payment)

    payload = b"{}"
    with patch("stripe.Webhook.construct_event", return_value={
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": payment_intent_id}},
    }):
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=payload,
            headers={"stripe-signature": "t=1,v1=x"},
        )

    assert resp.status_code == 200
    await db.refresh(payment)
    await db.refresh(enrollment)
    assert payment.status == "refunded"
    assert enrollment.status == "unenrolled"


@pytest.mark.asyncio
async def test_list_payments_returns_history(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /users/me/payments returns the student's payment records."""
    instructor, _ = await _make_user(db, f"instr3-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, token = await _make_user(db, f"stu3-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_paid_course(db, instructor.id)

    db.add(Payment(
        user_id=student.id,
        course_id=course.id,
        amount_cents=4999,
        status="completed",
        provider_payment_id=f"cs_{uuid.uuid4().hex}",
    ))
    await db.commit()

    resp = await client.get(
        "/api/v1/users/me/payments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 1
    assert data[0]["amount_cents"] == 4999
    assert data[0]["status"] == "completed"
