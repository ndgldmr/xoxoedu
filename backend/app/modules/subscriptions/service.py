"""Business logic for market-based subscription billing.

Covers:
- Country → market resolution
- Stripe subscription checkout creation
- Webhook event handling (checkout, subscription lifecycle, invoices)
- Student and admin read helpers
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import stripe
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import (
    InvalidWebhookSignature,
    NoMarketForCountry,
    SubscriptionNotFound,
)
from app.db.models.subscription import (
    BillingCycle,
    PaymentTransaction,
    Subscription,
    SubscriptionPlan,
)

# ── Country → Market mapping ─────────────────────────────────────────────────

_COUNTRY_TO_MARKET: dict[str, str] = {
    "BR": "BR",
    "CA": "CA",
    **{
        c: "EU"
        for c in [
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
            "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
            "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        ]
    },
}

_STRIPE_STATUS_MAP: dict[str, str] = {
    "active":   "active",
    "past_due": "past_due",
    "trialing": "trialing",
    "canceled": "canceled",
    "unpaid":   "past_due",
    "paused":   "past_due",
}


def resolve_market(country: str | None) -> str:
    """Map an ISO-3166-1 alpha-2 country code to an internal market code.

    Args:
        country: Two-letter country code from ``User.country`` (may be ``None``).

    Returns:
        Market code: ``"BR"``, ``"CA"``, or ``"EU"``.

    Raises:
        NoMarketForCountry: If ``country`` is ``None`` or not covered by any
            launch market.
    """
    if not country:
        raise NoMarketForCountry()
    market = _COUNTRY_TO_MARKET.get(country.upper())
    if market is None:
        raise NoMarketForCountry()
    return market


def _stripe_client() -> stripe.StripeClient:
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


# ── Plan helpers ──────────────────────────────────────────────────────────────


async def get_active_plan_for_market(
    db: AsyncSession, market: str
) -> SubscriptionPlan:
    """Return the active subscription plan for a market.

    Args:
        db: Async database session.
        market: Internal market code (e.g. ``"BR"``).

    Returns:
        The matching ``SubscriptionPlan``.

    Raises:
        NoMarketForCountry: If no active plan exists for the market.
    """
    plan = await db.scalar(
        select(SubscriptionPlan).where(
            SubscriptionPlan.market == market,
            SubscriptionPlan.is_active.is_(True),
        ).order_by(SubscriptionPlan.created_at.desc())
    )
    if plan is None:
        raise NoMarketForCountry()
    return plan


# ── Stripe customer helpers ───────────────────────────────────────────────────


async def get_or_create_stripe_customer(
    db: AsyncSession,
    stripe_client: stripe.StripeClient,
    user: Any,
) -> str:
    """Return an existing Stripe customer ID for the user or create a new one.

    Each student maps to exactly one Stripe Customer for life.  We look up any
    existing ``Subscription`` row that already holds a ``stripe_customer_id``
    for this user.  If none exists we create a new Stripe Customer and return
    the new ``cus_…`` identifier (the caller is responsible for persisting it
    on the new subscription row).

    Args:
        db: Async database session.
        stripe_client: Initialised ``stripe.StripeClient`` instance.
        user: The ``User`` ORM object (needs ``.id`` and ``.email``).

    Returns:
        Stripe Customer ID string (``"cus_…"``).
    """
    existing = await db.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.stripe_customer_id.isnot(None),
        ).order_by(Subscription.created_at.desc()).limit(1)
    )
    if existing and existing.stripe_customer_id:
        return existing.stripe_customer_id

    customer = stripe_client.customers.create(
        params={
            "email": user.email,
            "metadata": {"user_id": str(user.id)},
        }
    )
    return customer.id


# ── Checkout ──────────────────────────────────────────────────────────────────


async def create_subscription_checkout(
    db: AsyncSession,
    user: Any,
) -> dict[str, Any]:
    """Create a Stripe Checkout session for a recurring subscription.

    Resolves the student's country to a launch market, looks up the active
    plan, creates or reuses the Stripe Customer, and creates a pending
    ``Subscription`` row before redirecting to Stripe.

    Args:
        db: Async database session.
        user: Authenticated ``User`` ORM object.

    Returns:
        Dict with ``checkout_url`` (str) and ``subscription_id`` (UUID).

    Raises:
        NoMarketForCountry: If the user's country is not covered by any
            launch market or has no active plan.
    """
    market = resolve_market(user.country)
    plan = await get_active_plan_for_market(db, market)

    client = _stripe_client()
    customer_id = await get_or_create_stripe_customer(db, client, user)

    # Create a pending subscription row BEFORE the Stripe API call so we can
    # embed its ID in the checkout metadata for webhook correlation.
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        market=plan.market,
        currency=plan.currency,
        amount_cents=plan.amount_cents,
        status="trialing",
        provider="stripe",
        stripe_customer_id=customer_id,
    )
    db.add(sub)
    await db.flush()  # get sub.id

    session = client.checkout.sessions.create(
        params={
            "customer": customer_id,
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price_data": {
                        "currency": plan.currency.lower(),
                        "unit_amount": plan.amount_cents,
                        "recurring": {"interval": plan.interval},
                        "product_data": {"name": f"XOXO Education — {plan.name}"},
                    },
                    "quantity": 1,
                }
            ],
            "mode": "subscription",
            "success_url": f"{settings.FRONTEND_URL}/dashboard?subscription=success",
            "cancel_url": f"{settings.FRONTEND_URL}/pricing?subscription=cancelled",
            "metadata": {
                "subscription_id": str(sub.id),
                "user_id": str(user.id),
            },
        }
    )

    await db.commit()
    return {"checkout_url": session.url, "subscription_id": sub.id}


# ── Webhook dispatcher ────────────────────────────────────────────────────────


async def handle_webhook(
    db: AsyncSession,
    payload: bytes,
    sig_header: str,
) -> dict[str, Any]:
    """Verify and dispatch an incoming Stripe subscription webhook event.

    Args:
        db: Async database session.
        payload: Raw request body bytes for HMAC verification.
        sig_header: Value of the ``Stripe-Signature`` HTTP header.

    Returns:
        ``{"received": True}`` on success.

    Raises:
        InvalidWebhookSignature: If signature verification fails.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_SUBSCRIPTION_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        raise InvalidWebhookSignature() from exc

    dispatch: dict[str, Any] = {
        "checkout.session.completed":    _on_checkout_completed,
        "customer.subscription.updated": _on_subscription_updated,
        "customer.subscription.deleted": _on_subscription_deleted,
        "invoice.payment_succeeded":     _on_invoice_payment_succeeded,
        "invoice.payment_failed":        _on_invoice_payment_failed,
    }
    handler = dispatch.get(event["type"])
    if handler:
        await handler(db, event["data"]["object"])

    return {"received": True}


# ── Webhook handlers ──────────────────────────────────────────────────────────


async def _on_checkout_completed(
    db: AsyncSession, session: dict[str, Any]
) -> None:
    """Activate the pending subscription after a successful checkout.

    Only processes sessions with ``mode == "subscription"`` so that the
    existing payments webhook can coexist on the same Stripe account without
    interference.
    """
    if session.get("mode") != "subscription":
        return

    sub_id_str = (session.get("metadata") or {}).get("subscription_id")
    if not sub_id_str:
        return

    sub = await db.get(Subscription, uuid.UUID(sub_id_str))
    if not sub:
        return

    stripe_sub_id = session.get("subscription")
    if stripe_sub_id:
        # Idempotency: skip if already set to the same value.
        if sub.provider_subscription_id and sub.provider_subscription_id == stripe_sub_id:
            return
        sub.provider_subscription_id = stripe_sub_id

    sub.status = "active"
    await db.commit()


async def _on_subscription_updated(
    db: AsyncSession, stripe_sub: dict[str, Any]
) -> None:
    """Sync subscription status and billing period from a Stripe update event."""
    provider_sub_id = stripe_sub.get("id")
    if not provider_sub_id:
        return

    sub = await db.scalar(
        select(Subscription).where(
            Subscription.provider_subscription_id == provider_sub_id
        )
    )
    if not sub:
        return

    stripe_status = stripe_sub.get("status")
    sub.status = _STRIPE_STATUS_MAP.get(stripe_status or "", "past_due")

    cps = stripe_sub.get("current_period_start")
    cpe = stripe_sub.get("current_period_end")
    if cps:
        sub.current_period_start = datetime.fromtimestamp(cps, tz=UTC)
    if cpe:
        sub.current_period_end = datetime.fromtimestamp(cpe, tz=UTC)

    if stripe_status == "canceled" and sub.canceled_at is None:
        sub.canceled_at = datetime.now(UTC)

    await db.commit()


async def _on_subscription_deleted(
    db: AsyncSession, stripe_sub: dict[str, Any]
) -> None:
    """Mark a subscription as canceled when Stripe fully terminates it."""
    provider_sub_id = stripe_sub.get("id")
    if not provider_sub_id:
        return

    sub = await db.scalar(
        select(Subscription).where(
            Subscription.provider_subscription_id == provider_sub_id
        )
    )
    if not sub:
        return

    sub.status = "canceled"
    if sub.canceled_at is None:
        sub.canceled_at = datetime.now(UTC)

    await db.commit()


async def _on_invoice_payment_succeeded(
    db: AsyncSession, invoice: dict[str, Any]
) -> None:
    """Record a successful invoice payment: update the subscription and billing cycle.

    - Sets subscription to ``active`` and syncs the period dates.
    - Upserts a ``BillingCycle`` row for this invoice.
    - Appends an immutable ``PaymentTransaction`` (idempotent via unique constraint).
    """
    stripe_sub_id = invoice.get("subscription")
    invoice_id = invoice.get("id")
    amount_paid = invoice.get("amount_paid", 0)
    currency = (invoice.get("currency") or "").upper()
    period_start = invoice.get("period_start")
    period_end = invoice.get("period_end")
    charge_id = invoice.get("charge")

    if not stripe_sub_id:
        return

    sub = await db.scalar(
        select(Subscription).where(
            Subscription.provider_subscription_id == stripe_sub_id
        )
    )
    if not sub:
        return

    sub.status = "active"
    if period_start:
        sub.current_period_start = datetime.fromtimestamp(period_start, tz=UTC)
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)

    # Upsert BillingCycle by provider_invoice_id.
    cycle = await db.scalar(
        select(BillingCycle).where(BillingCycle.provider_invoice_id == invoice_id)
    ) if invoice_id else None

    cycle_was_paid = cycle.status == "paid" if cycle is not None else False
    if cycle is None:
        due_date = (
            date.fromtimestamp(period_start) if period_start else date.today()
        )
        cycle = BillingCycle(
            subscription_id=sub.id,
            due_date=due_date,
            amount_cents=amount_paid,
            currency=currency or sub.currency,
            provider_invoice_id=invoice_id,
        )
        db.add(cycle)
        await db.flush()

    cycle.status = "paid"
    cycle.paid_at = datetime.now(UTC)

    # Append PaymentTransaction — guarded by unique constraint on provider_transaction_id.
    if charge_id:
        existing_tx = await db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == charge_id
            )
        )
        if existing_tx is None:
            db.add(
                PaymentTransaction(
                    user_id=sub.user_id,
                    subscription_id=sub.id,
                    billing_cycle_id=cycle.id,
                    amount_cents=amount_paid,
                    currency=currency or sub.currency,
                    status="succeeded",
                    provider="stripe",
                    provider_transaction_id=charge_id,
                    provider_payload=invoice,
                )
            )

    if cycle_was_paid:
        await db.commit()
        return

    from app.modules.notifications import service as notification_service

    notification = notification_service.build_payment_processed_notification(
        recipient_id=sub.user_id,
        subscription_id=sub.id,
        billing_cycle_id=cycle.id,
        due_date=cycle.due_date,
        amount_cents=cycle.amount_cents,
        currency=cycle.currency,
        provider_invoice_id=cycle.provider_invoice_id,
        provider_transaction_id=charge_id,
    )
    await notification_service.commit_notification_and_dispatch(
        db,
        notification=notification,
    )


async def _on_invoice_payment_failed(
    db: AsyncSession, invoice: dict[str, Any]
) -> None:
    """Record a failed invoice payment: set past_due and mark the billing cycle.

    - Sets subscription to ``past_due``.
    - Upserts a ``BillingCycle`` row with ``status="failed"``.
    - Appends an immutable ``PaymentTransaction`` (idempotent via unique constraint).
    """
    stripe_sub_id = invoice.get("subscription")
    invoice_id = invoice.get("id")
    amount_due = invoice.get("amount_due", 0)
    currency = (invoice.get("currency") or "").upper()
    period_start = invoice.get("period_start")
    charge_id = invoice.get("charge")

    if not stripe_sub_id:
        return

    sub = await db.scalar(
        select(Subscription).where(
            Subscription.provider_subscription_id == stripe_sub_id
        )
    )
    if not sub:
        return

    sub.status = "past_due"

    cycle = await db.scalar(
        select(BillingCycle).where(BillingCycle.provider_invoice_id == invoice_id)
    ) if invoice_id else None

    cycle_was_failed = cycle.status == "failed" if cycle is not None else False
    if cycle is None:
        due_date = (
            date.fromtimestamp(period_start) if period_start else date.today()
        )
        cycle = BillingCycle(
            subscription_id=sub.id,
            due_date=due_date,
            amount_cents=amount_due,
            currency=currency or sub.currency,
            provider_invoice_id=invoice_id,
        )
        db.add(cycle)
        await db.flush()

    cycle.status = "failed"

    if charge_id:
        existing_tx = await db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == charge_id
            )
        )
        if existing_tx is None:
            db.add(
                PaymentTransaction(
                    user_id=sub.user_id,
                    subscription_id=sub.id,
                    billing_cycle_id=cycle.id,
                    amount_cents=amount_due,
                    currency=currency or sub.currency,
                    status="failed",
                    provider="stripe",
                    provider_transaction_id=charge_id,
                    provider_payload=invoice,
                )
            )

    if cycle_was_failed:
        await db.commit()
        return

    from app.modules.notifications import service as notification_service

    notification = notification_service.build_payment_failed_notification(
        recipient_id=sub.user_id,
        subscription_id=sub.id,
        billing_cycle_id=cycle.id,
        due_date=cycle.due_date,
        amount_cents=cycle.amount_cents,
        currency=cycle.currency,
        provider_invoice_id=cycle.provider_invoice_id,
        provider_transaction_id=charge_id,
    )
    await notification_service.commit_notification_and_dispatch(
        db,
        notification=notification,
    )


# ── Student read helpers ──────────────────────────────────────────────────────


async def get_my_subscription(
    db: AsyncSession, user_id: uuid.UUID
) -> Subscription | None:
    """Return the most recent subscription for a student.

    Args:
        db: Async database session.
        user_id: Authenticated student UUID.

    Returns:
        The most recent ``Subscription`` or ``None`` if the student has never
        subscribed.
    """
    return await db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )


async def list_my_billing_cycles(
    db: AsyncSession,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[BillingCycle], int]:
    """Return paginated billing cycles for the student's most recent subscription.

    Args:
        db: Async database session.
        user_id: Authenticated student UUID.
        skip: Number of rows to skip.
        limit: Maximum rows to return.

    Returns:
        Tuple of (rows, total_count).
    """
    sub = await get_my_subscription(db, user_id)
    if sub is None:
        return [], 0

    base_q = select(BillingCycle).where(BillingCycle.subscription_id == sub.id)
    total: int = await db.scalar(select(func.count()).select_from(base_q.subquery())) or 0
    rows = await db.scalars(
        base_q.order_by(BillingCycle.due_date.desc()).offset(skip).limit(limit)
    )
    return list(rows), total


# ── Admin read helpers ────────────────────────────────────────────────────────


async def admin_list_subscriptions(
    db: AsyncSession,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Subscription], int]:
    """Return paginated subscriptions for admin inspection.

    Args:
        db: Async database session.
        status: Optional filter by subscription status.
        skip: Number of rows to skip.
        limit: Maximum rows to return.

    Returns:
        Tuple of (rows, total_count).
    """
    base_q = select(Subscription).options(selectinload(Subscription.user))
    if status:
        base_q = base_q.where(Subscription.status == status)

    total: int = await db.scalar(select(func.count()).select_from(base_q.subquery())) or 0
    rows = await db.scalars(
        base_q.order_by(Subscription.created_at.desc()).offset(skip).limit(limit)
    )
    return list(rows), total


async def admin_get_subscription(
    db: AsyncSession, subscription_id: uuid.UUID
) -> Subscription:
    """Return a single subscription with its subscriber loaded.

    Args:
        db: Async database session.
        subscription_id: UUID of the subscription.

    Returns:
        The ``Subscription`` ORM object with ``user`` relationship loaded.

    Raises:
        SubscriptionNotFound: If the subscription does not exist.
    """
    sub = await db.scalar(
        select(Subscription)
        .where(Subscription.id == subscription_id)
        .options(selectinload(Subscription.user))
    )
    if sub is None:
        raise SubscriptionNotFound()
    return sub


async def admin_list_billing_cycles(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[BillingCycle], int]:
    """Return paginated billing cycles for a specific subscription.

    Args:
        db: Async database session.
        subscription_id: UUID of the parent subscription.
        skip: Number of rows to skip.
        limit: Maximum rows to return.

    Returns:
        Tuple of (rows, total_count).

    Raises:
        SubscriptionNotFound: If the subscription does not exist.
    """
    # Verify the subscription exists first.
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        raise SubscriptionNotFound()

    base_q = select(BillingCycle).where(BillingCycle.subscription_id == subscription_id)
    total: int = await db.scalar(select(func.count()).select_from(base_q.subquery())) or 0
    rows = await db.scalars(
        base_q.order_by(BillingCycle.due_date.desc()).offset(skip).limit(limit)
    )
    return list(rows), total
