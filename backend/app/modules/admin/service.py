"""Business logic for admin user, coupon, and payment management operations."""

import uuid

import stripe
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import (
    CouponAlreadyExists,
    CouponNotFound,
    PaymentNotFound,
    RefundFailed,
    UserNotFound,
)
from app.db.models.coupon import Coupon
from app.db.models.enrollment import Enrollment
from app.db.models.payment import Payment
from app.db.models.user import User
from app.modules.admin.schemas import (
    AdminPaymentOut,
    CouponCreateIn,
    CouponUpdateIn,
    RefundOut,
)


async def list_users(db: AsyncSession, skip: int, limit: int) -> tuple[list[User], int]:
    """Return a paginated list of all users with the total count.

    Args:
        db: Async database session.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(users, total)`` where ``total`` is the unfiltered row count.
    """
    count_result = await db.execute(select(User))
    total = len(count_result.scalars().all())

    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def update_role(db: AsyncSession, user_id: uuid.UUID, role: str) -> User:
    """Change the role of a user by ID.

    Args:
        db: Async database session.
        user_id: UUID of the user to update.
        role: The new role string (e.g. ``"admin"``, ``"instructor"``, ``"student"``).

    Returns:
        The updated ``User`` ORM instance.

    Raises:
        UserNotFound: If no user with that ID exists.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Hard-delete a user record by ID.

    Args:
        db: Async database session.
        user_id: UUID of the user to delete.

    Raises:
        UserNotFound: If no user with that ID exists.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


# ── Coupons ────────────────────────────────────────────────────────────────────

async def create_coupon(db: AsyncSession, data: CouponCreateIn) -> Coupon:
    """Create a new discount coupon.

    Args:
        db: Async database session.
        data: Validated coupon creation payload.

    Returns:
        The created ``Coupon`` ORM instance.

    Raises:
        CouponAlreadyExists: If a coupon with the same code already exists.
    """
    existing = await db.scalar(select(Coupon).where(Coupon.code == data.code))
    if existing:
        raise CouponAlreadyExists()

    coupon = Coupon(
        code=data.code,
        discount_type=data.discount_type,
        discount_value=data.discount_value,
        max_uses=data.max_uses,
        applies_to=[str(cid) for cid in data.applies_to] if data.applies_to else None,
        expires_at=data.expires_at,
    )
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def list_coupons(
    db: AsyncSession, skip: int, limit: int
) -> tuple[list[Coupon], int]:
    """Return a paginated list of all coupons, newest first.

    Args:
        db: Async database session.
        skip: Number of rows to skip.
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(coupons, total)``.
    """
    from sqlalchemy import func
    base = select(Coupon)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(Coupon.created_at.desc()).offset(skip).limit(limit)
    )
    return list(rows.all()), total or 0


async def update_coupon(
    db: AsyncSession, coupon_id: uuid.UUID, data: CouponUpdateIn
) -> Coupon:
    """Update a coupon's expiry date and/or usage cap.

    Args:
        db: Async database session.
        coupon_id: UUID of the coupon to update.
        data: Fields to update.

    Returns:
        The updated ``Coupon`` ORM instance.

    Raises:
        CouponNotFound: If no coupon with that ID exists.
    """
    coupon = await db.get(Coupon, coupon_id)
    if not coupon:
        raise CouponNotFound()
    coupon.expires_at = data.expires_at
    coupon.max_uses = data.max_uses
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def delete_coupon(db: AsyncSession, coupon_id: uuid.UUID) -> None:
    """Hard-delete a coupon by ID.

    Args:
        db: Async database session.
        coupon_id: UUID of the coupon to delete.

    Raises:
        CouponNotFound: If no coupon with that ID exists.
    """
    coupon = await db.get(Coupon, coupon_id)
    if not coupon:
        raise CouponNotFound()
    await db.delete(coupon)
    await db.commit()


# ── Payments ───────────────────────────────────────────────────────────────────

async def list_payments_admin(
    db: AsyncSession,
    course_id: uuid.UUID | None,
    status: str | None,
    skip: int,
    limit: int,
) -> tuple[list[AdminPaymentOut], int]:
    """Return a paginated, filterable list of all payments across the platform.

    Args:
        db: Async database session.
        course_id: Optional filter by course.
        status: Optional filter by payment status.
        skip: Number of rows to skip.
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(payments, total)``.
    """
    from sqlalchemy import func
    base = select(Payment)
    if course_id:
        base = base.where(Payment.course_id == course_id)
    if status:
        base = base.where(Payment.status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.options(selectinload(Payment.user), selectinload(Payment.course))
        .order_by(Payment.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    results: list[AdminPaymentOut] = []
    for p in rows:
        out = AdminPaymentOut.model_validate(p)
        out.user_email = p.user.email if p.user else None
        out.course_title = p.course.title if p.course else None
        results.append(out)
    return results, total or 0


async def refund_payment(db: AsyncSession, payment_id: uuid.UUID) -> RefundOut:
    """Trigger a Stripe refund for a completed payment.

    Retrieves the Stripe Checkout Session to resolve the payment intent, then
    creates a refund via the Stripe API.  Updates the ``Payment`` and any active
    ``Enrollment`` to ``"refunded"`` status on success.

    Args:
        db: Async database session.
        payment_id: UUID of the payment to refund.

    Returns:
        A ``RefundOut`` with the Stripe refund ID.

    Raises:
        PaymentNotFound: If no payment with that ID exists.
        RefundFailed: If the payment is not in ``"completed"`` state, or if the
            Stripe API call fails.
    """
    payment = await db.scalar(
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.user), selectinload(Payment.course))
    )
    if not payment:
        raise PaymentNotFound()

    if payment.status != "completed":
        raise RefundFailed(f"Cannot refund a payment with status '{payment.status}'")

    try:
        client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)
        session = client.checkout.sessions.retrieve(payment.provider_payment_id)
        payment_intent_id = session.payment_intent
        refund = client.refunds.create(params={"payment_intent": payment_intent_id})
    except stripe.StripeError as exc:
        raise RefundFailed() from exc

    payment.status = "refunded"
    await db.flush()

    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == payment.user_id,
            Enrollment.course_id == payment.course_id,
            Enrollment.status == "active",
        )
    )
    if enrollment:
        enrollment.status = "refunded"

    await db.commit()
    return RefundOut(
        payment_id=payment.id,
        status="refunded",
        stripe_refund_id=refund.id,
    )
