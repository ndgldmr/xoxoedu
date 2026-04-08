"""Pydantic schemas for coupon validation."""

import uuid

from pydantic import BaseModel


class CouponValidateRequest(BaseModel):
    code: str
    course_id: uuid.UUID
    original_amount_cents: int


class CouponValidateResponse(BaseModel):
    valid: bool
    coupon_id: uuid.UUID
    discount_type: str
    discount_value: float
    discount_amount_cents: int
    final_amount_cents: int
