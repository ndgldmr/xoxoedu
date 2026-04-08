"""Business logic for coupon validation and redemption."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CouponExpired,
    CouponNotApplicable,
    CouponNotFound,
    CouponUsageExceeded,
)
from app.db.models.coupon import Coupon
from app.modules.coupons.schemas import CouponValidateResponse


def _calculate_discount(coupon: Coupon, original_amount_cents: int) -> int:
    """Return the discount in cents for the given coupon and original price.

    Args:
        coupon: The validated ``Coupon`` ORM instance.
        original_amount_cents: The full price before discount, in cents.

    Returns:
        The discount amount in cents, capped at ``original_amount_cents``.
    """
    if coupon.discount_type == "percentage":
        discount = int(original_amount_cents * float(coupon.discount_value) / 100)
    else:
        discount = int(coupon.discount_value)
    return min(discount, original_amount_cents)


async def validate_coupon(
    db: AsyncSession,
    code: str,
    course_id: uuid.UUID,
    original_amount_cents: int,
) -> CouponValidateResponse:
    """Validate a coupon code and return the computed discount.

    Args:
        db: Async database session.
        code: The coupon code string to look up.
        course_id: The course the student wants to apply the coupon to.
        original_amount_cents: The course's full price in cents.

    Returns:
        A ``CouponValidateResponse`` with discount details and final price.

    Raises:
        CouponNotFound: If no coupon with that code exists.
        CouponExpired: If the coupon's expiry date has passed.
        CouponUsageExceeded: If the coupon has hit its ``max_uses`` cap.
        CouponNotApplicable: If the coupon is scoped and does not cover this course.
    """
    coupon = await db.scalar(select(Coupon).where(Coupon.code == code))
    if not coupon:
        raise CouponNotFound()

    now = datetime.now(UTC)
    if coupon.expires_at and coupon.expires_at < now:
        raise CouponExpired()

    if coupon.max_uses is not None and coupon.uses_count >= coupon.max_uses:
        raise CouponUsageExceeded()

    if coupon.applies_to is not None and str(course_id) not in coupon.applies_to:
        raise CouponNotApplicable()

    discount_cents = _calculate_discount(coupon, original_amount_cents)
    return CouponValidateResponse(
        valid=True,
        coupon_id=coupon.id,
        discount_type=coupon.discount_type,
        discount_value=float(coupon.discount_value),
        discount_amount_cents=discount_cents,
        final_amount_cents=original_amount_cents - discount_cents,
    )


async def redeem_coupon(db: AsyncSession, coupon_id: uuid.UUID) -> None:
    """Atomically increment the coupon's ``uses_count``.

    Args:
        db: Async database session.
        coupon_id: UUID of the coupon to redeem.
    """
    await db.execute(
        update(Coupon)
        .where(Coupon.id == coupon_id)
        .values(uses_count=Coupon.uses_count + 1)
    )
