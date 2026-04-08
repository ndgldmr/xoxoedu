"""ORM model for payment records."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course
    from app.db.models.user import User


class Payment(Base, UUIDMixin, TimestampMixin):
    """Records a single payment attempt for a course.

    Attributes:
        user_id: The student who initiated the payment.
        course_id: The course being purchased.
        amount_cents: Charged amount in the smallest currency unit (e.g. US cents).
        currency: ISO 4217 currency code, defaults to ``"usd"``.
        status: Lifecycle state — ``pending``, ``completed``, ``failed``, or ``refunded``.
        provider: Payment provider name, defaults to ``"stripe"``.
        provider_payment_id: The Stripe Checkout Session ID or charge ID.
    """

    __tablename__ = "payments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="stripe")
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])
