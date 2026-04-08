"""ORM model for discount coupons."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Coupon(Base, UUIDMixin, TimestampMixin):
    """A discount coupon that can be applied at checkout.

    Attributes:
        code: Unique human-readable coupon code (e.g. ``"SUMMER20"``).
        discount_type: Either ``"percentage"`` (0–100) or ``"fixed"`` (cents).
        discount_value: The magnitude of the discount — a percentage or a cent amount.
        max_uses: Maximum total redemptions; ``None`` means unlimited.
        uses_count: How many times this coupon has been redeemed.
        applies_to: List of course ID strings this coupon is restricted to;
            ``None`` means the coupon is global and applies to any course.
        expires_at: Optional expiry timestamp; ``None`` means the coupon never expires.
    """

    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applies_to: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
