"""Pydantic schemas for admin-only request bodies and responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.core.rbac import Role


class RoleUpdateIn(BaseModel):
    """Payload for ``PATCH /admin/users/{user_id}/role``."""

    role: Role


# ── Coupons ────────────────────────────────────────────────────────────────────

class CouponCreateIn(BaseModel):
    """Payload for ``POST /admin/coupons``."""

    code: str
    discount_type: str
    discount_value: float
    max_uses: int | None = None
    applies_to: list[uuid.UUID] | None = None
    expires_at: datetime | None = None

    @field_validator("discount_type")
    @classmethod
    def validate_discount_type(cls, v: str) -> str:
        if v not in {"percentage", "fixed"}:
            raise ValueError("discount_type must be 'percentage' or 'fixed'")
        return v

    @field_validator("discount_value")
    @classmethod
    def validate_discount_value(cls, v: float) -> float:
        if v < 0:
            raise ValueError("discount_value must be non-negative")
        return v


class CouponUpdateIn(BaseModel):
    """Payload for ``PATCH /admin/coupons/{id}``."""

    expires_at: datetime | None = None
    max_uses: int | None = None


class CouponOut(BaseModel):
    """Response schema for a coupon."""

    id: uuid.UUID
    code: str
    discount_type: str
    discount_value: float
    max_uses: int | None
    uses_count: int
    applies_to: list[str] | None
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payments ───────────────────────────────────────────────────────────────────

class AdminPaymentOut(BaseModel):
    """Response schema for a payment record in the admin view."""

    id: uuid.UUID
    user_id: uuid.UUID
    course_id: uuid.UUID
    amount_cents: int
    currency: str
    status: str
    provider_payment_id: str | None
    created_at: datetime
    user_email: str | None = None
    course_title: str | None = None

    model_config = {"from_attributes": True}


class RefundOut(BaseModel):
    """Response schema after a successful refund."""

    payment_id: uuid.UUID
    status: str
    stripe_refund_id: str
