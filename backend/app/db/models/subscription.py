"""ORM models for subscription plans, subscriptions, billing cycles, and payment transactions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class SubscriptionPlan(Base, UUIDMixin, TimestampMixin):
    """Catalog entry describing a recurring monthly offering by market.

    Launch plans (seedable, not hard-coded in service logic):
    - Brazil: ``BRL 1000`` (BRL 10.00 / month)
    - Canada: ``CAD 1000`` (CAD 10.00 / month)
    - Europe: ``EUR 1499`` (EUR 14.99 / month)

    Amounts are stored as integer cents (minor units) to mirror the Stripe
    API convention and avoid floating-point precision issues.

    Attributes:
        name: Human-readable plan label (e.g. ``"Brazil Monthly"``).
        market: Regional market code (``"BR"``, ``"CA"``, ``"EU"``).
        currency: ISO 4217 currency code (``"BRL"``, ``"CAD"``, ``"EUR"``).
        amount_cents: Recurring charge in the smallest currency unit.
        interval: Billing frequency; always ``"month"`` at launch.
        is_active: Whether this plan is available for new subscriptions.
        subscriptions: All ``Subscription`` rows referencing this plan.
    """

    __tablename__ = "subscription_plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False, default="month")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription", back_populates="plan"
    )


class Subscription(Base, UUIDMixin, TimestampMixin):
    """Student-level recurring access grant.

    Stores a pricing snapshot (``market``, ``currency``, ``amount_cents``) at
    subscription creation time so that historical billing reports remain stable
    if plan pricing changes later.

    Access to the platform depends on ``status == "active"``.  Webhook handlers
    transition status when Stripe reports renewal success, payment failure, or
    cancellation.

    Attributes:
        user_id: FK to the subscriber.
        plan_id: FK to the ``SubscriptionPlan`` at creation time; nullable so
            the subscription survives if the plan record is later removed.
        market: Market code snapshot (e.g. ``"BR"``).
        currency: Currency snapshot (e.g. ``"BRL"``).
        amount_cents: Amount snapshot in minor units.
        status: Lifecycle state: ``active``, ``past_due``, ``canceled``,
            ``trialing``.
        provider: Payment provider name (``"stripe"``).
        provider_subscription_id: Stripe Subscription ID; unique across the
            table to prevent duplicate webhook processing.
        current_period_start / current_period_end: Billing window for the
            current cycle, as reported by the provider.
        canceled_at: Set when the subscription enters ``canceled`` state.
        user: The subscribing ``User``.
        plan: The ``SubscriptionPlan`` at subscription creation; may be
            ``None`` if the plan was later removed.
        billing_cycles: All ``BillingCycle`` records for this subscription.
        transactions: All ``PaymentTransaction`` records for this subscription.
    """

    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    plan: Mapped[SubscriptionPlan | None] = relationship(
        "SubscriptionPlan", back_populates="subscriptions"
    )
    billing_cycles: Mapped[list[BillingCycle]] = relationship(
        "BillingCycle", back_populates="subscription"
    )
    transactions: Mapped[list[PaymentTransaction]] = relationship(
        "PaymentTransaction", back_populates="subscription"
    )


class BillingCycle(Base, UUIDMixin, TimestampMixin):
    """One recurring monthly billing period for a subscription.

    Tracks the due date, payment state, reminder status, and optional provider
    invoice identifiers for one calendar billing window.

    Status lifecycle: ``pending`` → ``paid`` or ``failed``; ``pending`` or
    ``failed`` → ``waived`` (admin action).

    Attributes:
        subscription_id: FK to the parent subscription.
        due_date: Calendar date the payment is due.
        paid_at: Set when the cycle transitions to ``paid``.
        amount_cents: Expected charge for this cycle in minor units.
        currency: ISO 4217 currency code for this cycle.
        status: Cycle state: ``pending``, ``paid``, ``failed``, ``waived``.
        reminder_sent_at: Set when the payment-due reminder notification was
            dispatched; ``None`` means no reminder has been sent yet.
        provider_invoice_id: Stripe Invoice ID for this billing period.
        subscription: The parent ``Subscription``.
        transactions: ``PaymentTransaction`` records tied to this cycle.
    """

    __tablename__ = "billing_cycles"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    subscription: Mapped[Subscription] = relationship(
        "Subscription", back_populates="billing_cycles"
    )
    transactions: Mapped[list[PaymentTransaction]] = relationship(
        "PaymentTransaction", back_populates="billing_cycle"
    )


class PaymentTransaction(Base, UUIDMixin):
    """Immutable log of a single provider payment event or billing state transition.

    This table is **append-only**.  Mutations should create new rows rather than
    updating existing ones.  There is no ``updated_at`` column by design.  Use
    this table for receipts, reconciliation, support tooling, and auditability.

    ``subscription_id`` and ``billing_cycle_id`` use ``SET NULL`` on delete so
    that orphan transaction records survive subscription cancellation and can
    still be used for refund processing and support lookups.

    Attributes:
        user_id: FK to the paying student; cascades on user delete.
        subscription_id: FK to the related subscription; nullable.
        billing_cycle_id: FK to the related billing cycle; nullable.
        amount_cents: Charge or credit amount in minor units.
        currency: ISO 4217 currency code.
        status: Transaction outcome: ``succeeded``, ``failed``, ``refunded``,
            ``pending``.
        provider: Payment provider name (``"stripe"``).
        provider_transaction_id: Stripe Charge or PaymentIntent ID; unique
            across the table to prevent duplicate processing.
        provider_payload: Raw provider webhook payload for auditability.
        created_at: DB-set immutable creation timestamp.
    """

    __tablename__ = "payment_transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    billing_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_cycles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    provider_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    subscription: Mapped[Subscription | None] = relationship(
        "Subscription", back_populates="transactions"
    )
    billing_cycle: Mapped[BillingCycle | None] = relationship(
        "BillingCycle", back_populates="transactions"
    )
