"""Business logic for Stripe Checkout and webhook processing."""

import uuid
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import (
    CourseNotFound,
    InvalidWebhookSignature,
)
from app.db.models.course import Course
from app.db.models.payment import Payment
from app.modules.coupons import service as coupon_service
from app.modules.payments.schemas import CheckoutResponse, PaymentOut


def _stripe_client() -> stripe.StripeClient:
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


async def create_checkout_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    coupon_code: str | None,
) -> CheckoutResponse:
    """Create a Stripe Checkout session for a paid course.

    Applies a coupon discount if provided.  Records a ``Payment`` row with
    status ``"pending"`` before redirecting the student to Stripe.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.
        course_id: UUID of the course being purchased.
        coupon_code: Optional coupon code to apply.

    Returns:
        A ``CheckoutResponse`` containing the Stripe-hosted checkout URL and the
        internal payment record ID.

    Raises:
        CourseNotFound: If the course does not exist.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise CourseNotFound()

    amount_cents = course.price_cents
    if coupon_code:
        validation = await coupon_service.validate_coupon(
            db, coupon_code, course_id, amount_cents
        )
        amount_cents = validation.final_amount_cents
        await coupon_service.redeem_coupon(db, validation.coupon_id)

    payment = Payment(
        user_id=user_id,
        course_id=course_id,
        amount_cents=amount_cents,
        status="pending",
    )
    db.add(payment)
    await db.flush()  # get payment.id before Stripe call

    client = _stripe_client()
    session = client.checkout.sessions.create(
        params={
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount_cents,
                        "product_data": {"name": course.title},
                    },
                    "quantity": 1,
                }
            ],
            "mode": "payment",
            "success_url": f"{settings.FRONTEND_URL}/courses/{course.slug}?payment=success",
            "cancel_url": f"{settings.FRONTEND_URL}/courses/{course.slug}?payment=cancelled",
            "metadata": {
                "payment_id": str(payment.id),
                "user_id": str(user_id),
                "course_id": str(course_id),
            },
        }
    )

    payment.provider_payment_id = session.id
    await db.commit()

    return CheckoutResponse(checkout_url=session.url, payment_id=payment.id)


async def handle_webhook(
    db: AsyncSession, payload: bytes, sig_header: str
) -> dict[str, Any]:
    """Verify and process an incoming Stripe webhook event.

    Dispatches on ``checkout.session.completed`` (enroll student) and
    ``charge.refunded`` (mark enrollment refunded).

    Args:
        db: Async database session.
        payload: Raw request body bytes for HMAC verification.
        sig_header: Value of the ``Stripe-Signature`` HTTP header.

    Returns:
        ``{"received": True}`` on success.

    Raises:
        InvalidWebhookSignature: If the signature check fails.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        raise InvalidWebhookSignature() from exc

    if event["type"] == "checkout.session.completed":
        await _handle_checkout_completed(db, event["data"]["object"])
    elif event["type"] == "charge.refunded":
        await _handle_charge_refunded(db, event["data"]["object"])

    return {"received": True}


async def _handle_checkout_completed(
    db: AsyncSession, session: dict[str, Any]
) -> None:
    payment_id_str = (session.get("metadata") or {}).get("payment_id")
    if not payment_id_str:
        return

    payment = await db.get(Payment, uuid.UUID(payment_id_str))
    if not payment:
        return

    payment.status = "completed"
    payment.provider_payment_id = session["id"]
    await db.flush()

    from app.modules.enrollments import service as enrollment_service
    await enrollment_service.enroll_paid(db, payment.user_id, payment.course_id, payment.id)
    await db.commit()


async def _handle_charge_refunded(db: AsyncSession, charge: dict[str, Any]) -> None:
    from app.db.models.enrollment import Enrollment

    payment_intent_id = charge.get("payment_intent")
    if not payment_intent_id:
        return

    payment = await db.scalar(
        select(Payment).where(Payment.provider_payment_id.contains(payment_intent_id))
    )
    if not payment:
        return

    payment.status = "refunded"

    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == payment.user_id,
            Enrollment.course_id == payment.course_id,
            Enrollment.status == "active",
        )
    )
    if enrollment:
        enrollment.status = "unenrolled"

    await db.commit()


async def list_payments(
    db: AsyncSession, user_id: uuid.UUID
) -> list[PaymentOut]:
    """Return all payment records for a student, newest first.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.

    Returns:
        List of ``PaymentOut`` schemas.
    """
    rows = await db.scalars(
        select(Payment)
        .where(Payment.user_id == user_id)
        .options(selectinload(Payment.course))
        .order_by(Payment.created_at.desc())
    )
    return [PaymentOut.model_validate(p) for p in rows]
