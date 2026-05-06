"""Integration tests for subscription checkout, webhooks, access control, and admin endpoints."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.notification import Notification, NotificationDelivery, NotificationPreference
from app.db.models.subscription import (
    BillingCycle,
    PaymentTransaction,
    Subscription,
    SubscriptionPlan,
)
from app.db.models.user import User
from app.modules.notifications.constants import NotificationDeliveryStatus, NotificationType


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _make_user(
    db: AsyncSession,
    email: str,
    role: str = "student",
    country: str | None = "BR",
) -> tuple[User, str]:
    local, domain = email.split("@")
    email = f"{local}_{uuid.uuid4().hex[:8]}@{domain}"
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass"),
        role=role,
        email_verified=True,
        display_name="Test User",
        country=country,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_plan(
    db: AsyncSession,
    market: str = "BR",
    currency: str = "BRL",
    amount_cents: int = 1000,
) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name=f"{market} Monthly Test",
        market=market,
        currency=currency,
        amount_cents=amount_cents,
        interval="month",
        is_active=True,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def _make_subscription(
    db: AsyncSession,
    user: User,
    plan: SubscriptionPlan,
    status: str = "active",
    provider_subscription_id: str | None = None,
    stripe_customer_id: str | None = None,
) -> Subscription:
    sub = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_id=plan.id,
        market=plan.market,
        currency=plan.currency,
        amount_cents=plan.amount_cents,
        status=status,
        provider="stripe",
        provider_subscription_id=provider_subscription_id or f"sub_{uuid.uuid4().hex}",
        stripe_customer_id=stripe_customer_id or f"cus_{uuid.uuid4().hex}",
        current_period_start=datetime.now(UTC),
        current_period_end=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.com"


def _mock_stripe_customer(customer_id: str = "cus_test123") -> MagicMock:
    customer = MagicMock()
    customer.id = customer_id
    return customer


def _mock_stripe_session(
    checkout_url: str = "https://checkout.stripe.com/pay/test",
    session_id: str = "cs_test_abc",
) -> MagicMock:
    session = MagicMock()
    session.url = checkout_url
    session.id = session_id
    return session


# ── Checkout tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_creates_pending_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /subscriptions/checkout creates a trialing subscription and returns checkout_url."""
    user, token = await _make_user(db, _unique_email("checkout"), country="BR")
    await _make_plan(db, market="BR", currency="BRL", amount_cents=1000)

    mock_customer = _mock_stripe_customer("cus_new_br")
    mock_session = _mock_stripe_session("https://stripe.com/checkout/test")

    with (
        patch(
            "app.modules.subscriptions.service._stripe_client"
        ) as mock_client_fn,
    ):
        mock_client = MagicMock()
        mock_client.customers.create.return_value = mock_customer
        mock_client.checkout.sessions.create.return_value = mock_session
        mock_client_fn.return_value = mock_client

        resp = await client.post(
            "/api/v1/subscriptions/checkout",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["checkout_url"] == "https://stripe.com/checkout/test"
    assert "subscription_id" in data

    sub = await db.scalar(
        select(Subscription).where(
            Subscription.id == uuid.UUID(data["subscription_id"])
        )
    )
    assert sub is not None
    assert sub.status == "trialing"
    assert sub.market == "BR"
    assert sub.currency == "BRL"
    assert sub.amount_cents == 1000
    assert sub.stripe_customer_id == "cus_new_br"


@pytest.mark.asyncio
async def test_checkout_unknown_country_returns_422(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Students without a recognised country get 422 NO_MARKET_FOR_COUNTRY."""
    user, token = await _make_user(db, _unique_email("no-country"), country=None)

    resp = await client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NO_MARKET_FOR_COUNTRY"


@pytest.mark.asyncio
async def test_checkout_reuses_existing_stripe_customer(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Two checkout requests for the same user create only one Stripe Customer."""
    user, token = await _make_user(db, _unique_email("reuse-cus"), country="CA")
    plan = await _make_plan(db, market="CA", currency="CAD", amount_cents=1000)

    # Seed an existing subscription with a stripe_customer_id for this user.
    await _make_subscription(
        db, user, plan, status="canceled", stripe_customer_id="cus_existing_ca"
    )

    mock_session = _mock_stripe_session()

    with (
        patch(
            "app.modules.subscriptions.service._stripe_client"
        ) as mock_client_fn,
    ):
        mock_client = MagicMock()
        mock_client.checkout.sessions.create.return_value = mock_session
        mock_client_fn.return_value = mock_client

        resp = await client.post(
            "/api/v1/subscriptions/checkout",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 201
    # customers.create should NOT have been called because one already exists.
    mock_client.customers.create.assert_not_called()

    # The new pending subscription should carry the existing customer ID.
    sub_id = uuid.UUID(resp.json()["data"]["subscription_id"])
    new_sub = await db.scalar(select(Subscription).where(Subscription.id == sub_id))
    assert new_sub is not None
    assert new_sub.stripe_customer_id == "cus_existing_ca"


# ── Webhook tests ─────────────────────────────────────────────────────────────


def _post_subscription_webhook(payload: dict) -> dict:
    """Return the event dict structure that stripe.Webhook.construct_event would return."""
    return payload


@pytest.mark.asyncio
async def test_webhook_checkout_completed_activates_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """checkout.session.completed (subscription mode) activates the pending subscription."""
    user, _ = await _make_user(db, _unique_email("wh-activate"))
    plan = await _make_plan(db)

    # Create a pending subscription row as the service would.
    sub = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_id=plan.id,
        market=plan.market,
        currency=plan.currency,
        amount_cents=plan.amount_cents,
        status="trialing",
        provider="stripe",
    )
    db.add(sub)
    await db.commit()

    stripe_sub_id = f"sub_{uuid.uuid4().hex}"
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_abc",
                "mode": "subscription",
                "subscription": stripe_sub_id,
                "metadata": {
                    "subscription_id": str(sub.id),
                    "user_id": str(user.id),
                },
            }
        },
    }

    with patch(
        "stripe.Webhook.construct_event", return_value=event
    ):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "test-sig"},
        )

    assert resp.status_code == 200

    await db.refresh(sub)
    assert sub.status == "active"
    assert sub.provider_subscription_id == stripe_sub_id


@pytest.mark.asyncio
async def test_webhook_checkout_completed_ignores_payment_mode(
    client: AsyncClient, db: AsyncSession
) -> None:
    """checkout.session.completed with mode=payment does not touch subscription rows."""
    user, _ = await _make_user(db, _unique_email("wh-payment-mode"))
    plan = await _make_plan(db, market="BR")

    sub = await _make_subscription(db, user, plan, status="trialing")
    original_status = sub.status

    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_pay",
                "mode": "payment",  # ← NOT subscription
                "metadata": {"subscription_id": str(sub.id), "user_id": str(user.id)},
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    await db.refresh(sub)
    assert sub.status == original_status  # unchanged


@pytest.mark.asyncio
async def test_webhook_subscription_updated_syncs_period(
    client: AsyncClient, db: AsyncSession
) -> None:
    """customer.subscription.updated refreshes period dates and status."""
    user, _ = await _make_user(db, _unique_email("wh-updated"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    sub = await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    new_start = 1_700_000_000
    new_end = new_start + 30 * 24 * 3600

    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": provider_sub_id,
                "status": "active",
                "current_period_start": new_start,
                "current_period_end": new_end,
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    await db.refresh(sub)
    assert sub.status == "active"
    assert sub.current_period_start is not None
    assert sub.current_period_end is not None


@pytest.mark.asyncio
async def test_webhook_subscription_updated_past_due(
    client: AsyncClient, db: AsyncSession
) -> None:
    """customer.subscription.updated with Stripe status past_due sets internal past_due."""
    user, _ = await _make_user(db, _unique_email("wh-pastdue"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    sub = await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": provider_sub_id,
                "status": "past_due",
                "current_period_start": None,
                "current_period_end": None,
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    await db.refresh(sub)
    assert sub.status == "past_due"


@pytest.mark.asyncio
async def test_webhook_subscription_deleted_cancels(
    client: AsyncClient, db: AsyncSession
) -> None:
    """customer.subscription.deleted marks the subscription as canceled."""
    user, _ = await _make_user(db, _unique_email("wh-deleted"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    sub = await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )
    assert sub.canceled_at is None

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": provider_sub_id}},
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    await db.refresh(sub)
    assert sub.status == "canceled"
    assert sub.canceled_at is not None


@pytest.mark.asyncio
async def test_webhook_invoice_payment_succeeded_creates_cycle_and_tx(
    client: AsyncClient, db: AsyncSession
) -> None:
    """invoice.payment_succeeded creates a paid BillingCycle and a PaymentTransaction."""
    user, _ = await _make_user(db, _unique_email("wh-inv-ok"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    sub = await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    invoice_id = f"in_{uuid.uuid4().hex}"
    charge_id = f"ch_{uuid.uuid4().hex}"
    period_start = 1_700_000_000

    event = {
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": provider_sub_id,
                "amount_paid": 1000,
                "currency": "brl",
                "period_start": period_start,
                "period_end": period_start + 30 * 24 * 3600,
                "charge": charge_id,
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200

    cycle = await db.scalar(
        select(BillingCycle).where(BillingCycle.provider_invoice_id == invoice_id)
    )
    assert cycle is not None
    assert cycle.status == "paid"
    assert cycle.paid_at is not None

    tx = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.provider_transaction_id == charge_id
        )
    )
    assert tx is not None
    assert tx.status == "succeeded"
    assert tx.user_id == user.id


@pytest.mark.asyncio
async def test_webhook_invoice_payment_succeeded_creates_notification_and_delivery(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A successful invoice payment creates one billing notification and queues delivery."""
    user, _ = await _make_user(db, _unique_email("wh-inv-notif"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    invoice_id = f"in_{uuid.uuid4().hex}"
    charge_id = f"ch_{uuid.uuid4().hex}"
    period_start = 1_700_000_000
    due_date = datetime.fromtimestamp(period_start, tz=UTC).date().isoformat()
    event = {
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": provider_sub_id,
                "amount_paid": 1000,
                "currency": "brl",
                "period_start": period_start,
                "period_end": period_start + 30 * 24 * 3600,
                "charge": charge_id,
            }
        },
    }

    with (
        patch("stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.notifications.tasks.send_notification_email.delay") as mock_delay,
        patch(
            "app.modules.notifications.service.publish_notification",
            new_callable=AsyncMock,
        ) as mock_publish,
    ):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    mock_delay.assert_called_once()
    mock_publish.assert_awaited_once()

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == user.id,
            Notification.type == NotificationType.PAYMENT_PROCESSED.value,
        )
    )
    assert notif is not None
    assert notif.event_metadata["provider_invoice_id"] == invoice_id
    assert notif.event_metadata["provider_transaction_id"] == charge_id
    assert notif.event_metadata["due_date"] == due_date

    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.QUEUED.value


@pytest.mark.asyncio
async def test_webhook_invoice_payment_succeeded_idempotent(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Replaying an invoice.payment_succeeded does not create duplicate transactions."""
    user, _ = await _make_user(db, _unique_email("wh-idem"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    sub = await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    invoice_id = f"in_{uuid.uuid4().hex}"
    charge_id = f"ch_{uuid.uuid4().hex}"

    event = {
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": provider_sub_id,
                "amount_paid": 1000,
                "currency": "brl",
                "period_start": 1_700_000_000,
                "period_end": 1_702_592_000,
                "charge": charge_id,
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        # Replay the same event.
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200

    # Only one PaymentTransaction row should exist for this charge.
    count = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.provider_transaction_id == charge_id
        )
    )
    assert count is not None  # exactly one row (scalar returns the row, not count)

    from sqlalchemy import func
    tx_count = await db.scalar(
        select(func.count()).select_from(
            select(PaymentTransaction)
            .where(PaymentTransaction.provider_transaction_id == charge_id)
            .subquery()
        )
    )
    assert tx_count == 1


@pytest.mark.asyncio
async def test_webhook_invoice_payment_succeeded_duplicate_event_does_not_duplicate_notification(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Replaying a successful invoice webhook does not enqueue another notification."""
    user, _ = await _make_user(db, _unique_email("wh-idem-notif"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    invoice_id = f"in_{uuid.uuid4().hex}"
    charge_id = f"ch_{uuid.uuid4().hex}"
    event = {
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": provider_sub_id,
                "amount_paid": 1000,
                "currency": "brl",
                "period_start": 1_700_000_000,
                "period_end": 1_702_592_000,
                "charge": charge_id,
            }
        },
    }

    with (
        patch("stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.notifications.tasks.send_notification_email.delay") as mock_delay,
        patch(
            "app.modules.notifications.service.publish_notification",
            new_callable=AsyncMock,
        ),
    ):
        await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    mock_delay.assert_called_once()

    from sqlalchemy import func

    notif_count = await db.scalar(
        select(func.count()).select_from(
            select(Notification)
            .where(
                Notification.recipient_id == user.id,
                Notification.type == NotificationType.PAYMENT_PROCESSED.value,
            )
            .subquery()
        )
    )
    assert notif_count == 1


@pytest.mark.asyncio
async def test_webhook_invoice_payment_failed_sets_past_due(
    client: AsyncClient, db: AsyncSession
) -> None:
    """invoice.payment_failed sets subscription to past_due, cycle to failed."""
    user, _ = await _make_user(db, _unique_email("wh-fail"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    sub = await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )

    invoice_id = f"in_{uuid.uuid4().hex}"
    charge_id = f"ch_{uuid.uuid4().hex}"

    event = {
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": provider_sub_id,
                "amount_due": 1000,
                "currency": "brl",
                "period_start": 1_700_000_000,
                "charge": charge_id,
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200

    await db.refresh(sub)
    assert sub.status == "past_due"

    cycle = await db.scalar(
        select(BillingCycle).where(BillingCycle.provider_invoice_id == invoice_id)
    )
    assert cycle is not None
    assert cycle.status == "failed"

    tx = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.provider_transaction_id == charge_id
        )
    )
    assert tx is not None
    assert tx.status == "failed"


@pytest.mark.asyncio
async def test_webhook_invoice_payment_failed_respects_disabled_email_preference(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Billing notifications still persist when email is disabled, but delivery is skipped."""
    user, _ = await _make_user(db, _unique_email("wh-fail-pref"))
    plan = await _make_plan(db)
    provider_sub_id = f"sub_{uuid.uuid4().hex}"
    await _make_subscription(
        db, user, plan, status="active", provider_subscription_id=provider_sub_id
    )
    pref = NotificationPreference(
        user_id=user.id,
        notification_type=NotificationType.PAYMENT_FAILED.value,
        in_app_enabled=True,
        email_enabled=False,
    )
    db.add(pref)
    await db.commit()

    invoice_id = f"in_{uuid.uuid4().hex}"
    event = {
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": provider_sub_id,
                "amount_due": 1000,
                "currency": "brl",
                "period_start": 1_700_000_000,
                "charge": f"ch_{uuid.uuid4().hex}",
            }
        },
    }

    with (
        patch("stripe.Webhook.construct_event", return_value=event),
        patch("app.modules.notifications.tasks.send_notification_email.delay") as mock_delay,
        patch(
            "app.modules.notifications.service.publish_notification",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    mock_delay.assert_not_called()

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == user.id,
            Notification.type == NotificationType.PAYMENT_FAILED.value,
        )
    )
    assert notif is not None

    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.SKIPPED.value


@pytest.mark.asyncio
async def test_send_billing_cycle_reminder_is_idempotent(
    db: AsyncSession,
) -> None:
    """Re-running the reminder task for one cycle creates exactly one notification."""
    from app.modules.notifications.tasks import send_billing_cycle_reminder

    user, _ = await _make_user(db, _unique_email("cycle-reminder"))
    plan = await _make_plan(db)
    sub = await _make_subscription(db, user, plan, status="active")
    cycle = BillingCycle(
        id=uuid.uuid4(),
        subscription_id=sub.id,
        due_date=datetime.now(UTC).date() + timedelta(days=3),
        amount_cents=1000,
        currency="BRL",
        status="pending",
        provider_invoice_id=f"in_{uuid.uuid4().hex}",
    )
    db.add(cycle)
    await db.commit()

    with patch("app.modules.notifications.tasks.send_notification_email.delay") as mock_delay:
        send_billing_cycle_reminder.run(str(cycle.id))
        send_billing_cycle_reminder.run(str(cycle.id))

    from sqlalchemy import func

    notif_count = await db.scalar(
        select(func.count()).select_from(
            select(Notification)
            .where(
                Notification.recipient_id == user.id,
                Notification.type == NotificationType.PAYMENT_DUE_SOON.value,
            )
            .subquery()
        )
    )
    assert notif_count == 1
    mock_delay.assert_called_once()

    await db.refresh(cycle)
    assert cycle.reminder_sent_at is not None

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == user.id,
            Notification.type == NotificationType.PAYMENT_DUE_SOON.value,
        )
    )
    assert notif is not None
    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.QUEUED.value


@pytest.mark.asyncio
async def test_enqueue_billing_due_reminders_only_enqueues_eligible_cycles(
    db: AsyncSession,
) -> None:
    """The coordinator enqueues only pending cycles due in three days."""
    from app.worker.maintenance import enqueue_billing_due_reminders

    user, _ = await _make_user(db, _unique_email("reminder-coordinator"))
    plan = await _make_plan(db)
    sub = await _make_subscription(db, user, plan, status="active")

    eligible = BillingCycle(
        id=uuid.uuid4(),
        subscription_id=sub.id,
        due_date=datetime.now(UTC).date() + timedelta(days=3),
        amount_cents=1000,
        currency="BRL",
        status="pending",
        provider_invoice_id=f"in_{uuid.uuid4().hex}",
    )
    wrong_date = BillingCycle(
        id=uuid.uuid4(),
        subscription_id=sub.id,
        due_date=datetime.now(UTC).date() + timedelta(days=2),
        amount_cents=1000,
        currency="BRL",
        status="pending",
        provider_invoice_id=f"in_{uuid.uuid4().hex}",
    )
    paid = BillingCycle(
        id=uuid.uuid4(),
        subscription_id=sub.id,
        due_date=datetime.now(UTC).date() + timedelta(days=3),
        amount_cents=1000,
        currency="BRL",
        status="paid",
        provider_invoice_id=f"in_{uuid.uuid4().hex}",
    )
    db.add_all([eligible, wrong_date, paid])
    await db.commit()

    with patch(
        "app.modules.notifications.tasks.send_billing_cycle_reminder.delay"
    ) as mock_delay:
        enqueue_billing_due_reminders.run()

    mock_delay.assert_called_once_with(str(eligible.id))


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A bad Stripe signature returns 400 INVALID_WEBHOOK_SIGNATURE."""
    import stripe

    with patch(
        "stripe.Webhook.construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad sig", sig_header="x"),
    ):
        resp = await client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            headers={"stripe-signature": "bad"},
        )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


# ── Student read tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_my_subscription_returns_active(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /users/me/subscription returns the student's current subscription."""
    user, token = await _make_user(db, _unique_email("get-sub"))
    plan = await _make_plan(db)
    sub = await _make_subscription(db, user, plan, status="active")

    resp = await client.get(
        "/api/v1/users/me/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(sub.id)
    assert data["status"] == "active"
    assert data["market"] == plan.market


@pytest.mark.asyncio
async def test_get_my_subscription_no_subscription_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /users/me/subscription returns 404 when the student has never subscribed."""
    _, token = await _make_user(db, _unique_email("no-sub"))

    resp = await client.get(
        "/api/v1/users/me/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_my_billing_cycles(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /users/me/subscription/billing-cycles returns paginated billing history."""
    user, token = await _make_user(db, _unique_email("cycles"))
    plan = await _make_plan(db)
    sub = await _make_subscription(db, user, plan, status="active")

    from datetime import date

    for i in range(3):
        cycle = BillingCycle(
            id=uuid.uuid4(),
            subscription_id=sub.id,
            due_date=date(2026, i + 1, 1),
            amount_cents=1000,
            currency="BRL",
            status="paid",
            provider_invoice_id=f"in_{uuid.uuid4().hex}",
        )
        db.add(cycle)
    await db.commit()

    resp = await client.get(
        "/api/v1/users/me/subscription/billing-cycles",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 3
    assert len(body["data"]) == 3


# ── Access-check tests ────────────────────────────────────────────────────────
#
# We test the require_active_subscription dependency via a dedicated endpoint
# that we temporarily wire up inside the test using dependency_overrides.
# Alternatively, any content endpoint that uses the dependency can be targeted.
# Here we verify the behaviour through the GET /users/me/subscription route which
# itself requires Role.STUDENT; for the subscription guard we need a route
# that explicitly uses require_active_subscription.  We wire a lightweight
# test route on the live app for isolation.


@pytest.mark.asyncio
async def test_access_denied_no_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student with no subscription gets 402 SUBSCRIPTION_REQUIRED."""
    from fastapi import Depends
    from fastapi.routing import APIRoute

    from app.dependencies import _active_subscription_guard
    from app.main import app as fastapi_app

    _, token = await _make_user(db, _unique_email("guard-none"))

    # Temporarily add a test route that requires active subscription.
    @fastapi_app.get("/api/v1/_test/subscription-guard", include_in_schema=False)
    async def _guard_test(
        _user: User = Depends(_active_subscription_guard),
    ) -> dict:
        return {"ok": True}

    try:
        resp = await client.get(
            "/api/v1/_test/subscription-guard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 402
        assert resp.json()["error"]["code"] == "SUBSCRIPTION_REQUIRED"
    finally:
        # Clean up the temporary route.
        fastapi_app.routes[:] = [
            r for r in fastapi_app.routes
            if not (isinstance(r, APIRoute) and r.path == "/api/v1/_test/subscription-guard")
        ]


@pytest.mark.asyncio
async def test_access_denied_past_due_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student with a past_due subscription gets 402 SUBSCRIPTION_REQUIRED."""
    from fastapi import Depends
    from fastapi.routing import APIRoute

    from app.dependencies import _active_subscription_guard
    from app.main import app as fastapi_app

    user, token = await _make_user(db, _unique_email("guard-pastdue"))
    plan = await _make_plan(db, market="BR")
    await _make_subscription(db, user, plan, status="past_due")

    @fastapi_app.get("/api/v1/_test/subscription-guard-pd", include_in_schema=False)
    async def _guard_test_pd(
        _user: User = Depends(_active_subscription_guard),
    ) -> dict:
        return {"ok": True}

    try:
        resp = await client.get(
            "/api/v1/_test/subscription-guard-pd",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 402
    finally:
        fastapi_app.routes[:] = [
            r for r in fastapi_app.routes
            if not (isinstance(r, APIRoute) and r.path == "/api/v1/_test/subscription-guard-pd")
        ]


@pytest.mark.asyncio
async def test_access_granted_active_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student with an active subscription passes the guard."""
    from fastapi import Depends
    from fastapi.routing import APIRoute

    from app.dependencies import _active_subscription_guard
    from app.main import app as fastapi_app

    user, token = await _make_user(db, _unique_email("guard-active"))
    plan = await _make_plan(db, market="BR")
    await _make_subscription(db, user, plan, status="active")

    @fastapi_app.get("/api/v1/_test/subscription-guard-ok", include_in_schema=False)
    async def _guard_test_ok(
        _user: User = Depends(_active_subscription_guard),
    ) -> dict:
        return {"ok": True}

    try:
        resp = await client.get(
            "/api/v1/_test/subscription-guard-ok",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    finally:
        fastapi_app.routes[:] = [
            r for r in fastapi_app.routes
            if not (isinstance(r, APIRoute) and r.path == "/api/v1/_test/subscription-guard-ok")
        ]


@pytest.mark.asyncio
async def test_access_granted_trialing_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student with a trialing subscription passes the guard."""
    from fastapi import Depends
    from fastapi.routing import APIRoute

    from app.dependencies import _active_subscription_guard
    from app.main import app as fastapi_app

    user, token = await _make_user(db, _unique_email("guard-trialing"))
    plan = await _make_plan(db, market="CA")
    await _make_subscription(db, user, plan, status="trialing")

    @fastapi_app.get("/api/v1/_test/subscription-guard-trial", include_in_schema=False)
    async def _guard_test_trial(
        _user: User = Depends(_active_subscription_guard),
    ) -> dict:
        return {"ok": True}

    try:
        resp = await client.get(
            "/api/v1/_test/subscription-guard-trial",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
    finally:
        fastapi_app.routes[:] = [
            r for r in fastapi_app.routes
            if not (isinstance(r, APIRoute) and r.path == "/api/v1/_test/subscription-guard-trial")
        ]


# ── Admin endpoint tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_list_subscriptions(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/subscriptions returns a paginated list with meta.total."""
    admin, admin_token = await _make_user(db, _unique_email("admin-list"), role="admin", country=None)
    user1, _ = await _make_user(db, _unique_email("sub-u1"))
    user2, _ = await _make_user(db, _unique_email("sub-u2"), country="CA")
    plan_br = await _make_plan(db, market="BR")
    plan_ca = await _make_plan(db, market="CA", currency="CAD")
    await _make_subscription(db, user1, plan_br, status="active")
    await _make_subscription(db, user2, plan_ca, status="canceled")

    resp = await client.get(
        "/api/v1/admin/subscriptions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 2
    assert isinstance(body["data"], list)
    # All rows include user_email.
    for row in body["data"]:
        assert "user_email" in row


@pytest.mark.asyncio
async def test_admin_list_subscriptions_filter_by_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/subscriptions?status=canceled returns only canceled rows."""
    admin, admin_token = await _make_user(db, _unique_email("admin-filter"), role="admin", country=None)
    user, _ = await _make_user(db, _unique_email("filter-u"))
    plan = await _make_plan(db, market="BR")
    await _make_subscription(db, user, plan, status="canceled")

    resp = await client.get(
        "/api/v1/admin/subscriptions?status=canceled",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(row["status"] == "canceled" for row in data)


@pytest.mark.asyncio
async def test_admin_get_subscription(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/subscriptions/{id} returns the subscription with user_email."""
    admin, admin_token = await _make_user(db, _unique_email("admin-get"), role="admin", country=None)
    user, _ = await _make_user(db, _unique_email("get-detail"))
    plan = await _make_plan(db)
    sub = await _make_subscription(db, user, plan, status="active")

    resp = await client.get(
        f"/api/v1/admin/subscriptions/{sub.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(sub.id)
    assert data["user_email"] == user.email


@pytest.mark.asyncio
async def test_admin_get_subscription_not_found(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/subscriptions/{id} returns 404 for an unknown ID."""
    admin, admin_token = await _make_user(db, _unique_email("admin-nf"), role="admin", country=None)

    resp = await client.get(
        f"/api/v1/admin/subscriptions/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_admin_list_billing_cycles(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/subscriptions/{id}/billing-cycles returns cycles for that subscription."""
    from datetime import date

    admin, admin_token = await _make_user(db, _unique_email("admin-cycles"), role="admin", country=None)
    user, _ = await _make_user(db, _unique_email("cycles-u"))
    plan = await _make_plan(db)
    sub = await _make_subscription(db, user, plan, status="active")

    for i in range(2):
        db.add(BillingCycle(
            id=uuid.uuid4(),
            subscription_id=sub.id,
            due_date=date(2026, i + 1, 1),
            amount_cents=1000,
            currency="BRL",
            status="paid",
            provider_invoice_id=f"in_{uuid.uuid4().hex}",
        ))
    await db.commit()

    resp = await client.get(
        f"/api/v1/admin/subscriptions/{sub.id}/billing-cycles",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert all(row["user_id"] == str(user.id) for row in body["data"])


@pytest.mark.asyncio
async def test_admin_endpoints_forbidden_for_student(
    client: AsyncClient, db: AsyncSession
) -> None:
    """All admin subscription endpoints return 403 for a student JWT."""
    _, student_token = await _make_user(db, _unique_email("student-forbidden"))

    routes = [
        "/api/v1/admin/subscriptions",
        f"/api/v1/admin/subscriptions/{uuid.uuid4()}",
        f"/api/v1/admin/subscriptions/{uuid.uuid4()}/billing-cycles",
    ]
    for route in routes:
        resp = await client.get(
            route,
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403, f"Expected 403 for {route}, got {resp.status_code}"
