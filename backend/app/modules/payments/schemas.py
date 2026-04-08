"""Pydantic schemas for payments."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    course_id: uuid.UUID
    coupon_code: str | None = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    payment_id: uuid.UUID


class PaymentOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    amount_cents: int
    currency: str
    status: str
    provider_payment_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
