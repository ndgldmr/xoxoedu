"""Pydantic schemas for subscription plans, subscriptions, and billing cycles."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class PlanOut(BaseModel):
    """Public representation of a subscription plan."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    market: str
    currency: str
    amount_cents: int
    interval: str
    is_active: bool


class SubscriptionOut(BaseModel):
    """Public representation of a student subscription."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    plan_id: uuid.UUID | None
    market: str
    currency: str
    amount_cents: int
    status: str
    provider: str | None
    provider_subscription_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    canceled_at: datetime | None
    created_at: datetime


class BillingCycleOut(BaseModel):
    """Public representation of a single billing cycle."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    subscription_id: uuid.UUID
    due_date: date
    paid_at: datetime | None
    amount_cents: int
    currency: str
    status: str
    provider_invoice_id: str | None
    created_at: datetime


class SubscriptionCheckoutOut(BaseModel):
    """Response returned after creating a subscription checkout session."""

    checkout_url: str
    subscription_id: uuid.UUID


class AdminSubscriptionOut(SubscriptionOut):
    """Admin-extended subscription view with subscriber email."""

    user_email: str


class AdminBillingCycleOut(BillingCycleOut):
    """Admin-extended billing cycle with subscriber user_id."""

    user_id: uuid.UUID
