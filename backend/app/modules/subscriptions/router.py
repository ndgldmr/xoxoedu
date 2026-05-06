"""FastAPI router for subscription checkout, student billing views, and admin billing ops."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SubscriptionNotFound
from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.db.session import get_db
from app.modules.subscriptions import service
from app.modules.subscriptions.schemas import (
    AdminBillingCycleOut,
    AdminSubscriptionOut,
    BillingCycleOut,
    SubscriptionCheckoutOut,
    SubscriptionOut,
)

router = APIRouter(tags=["subscriptions"])
admin_router = APIRouter(
    prefix="/admin",
    tags=["subscriptions"],
    dependencies=[require_role(Role.ADMIN)],
)


@router.post("/subscriptions/checkout", status_code=201)
async def create_subscription_checkout(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Initiate a Stripe Checkout session for a recurring subscription."""
    result = await service.create_subscription_checkout(db, current_user)
    return ok(SubscriptionCheckoutOut(**result).model_dump())


@router.post("/subscriptions/webhook", status_code=200)
async def subscription_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str = Header(alias="stripe-signature"),
) -> dict:
    """Receive and process Stripe subscription lifecycle webhook events."""
    payload = await request.body()
    result = await service.handle_webhook(db, payload, stripe_signature)
    return result


@router.get("/users/me/subscription")
async def get_my_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the authenticated student's current subscription."""
    sub = await service.get_my_subscription(db, current_user.id)
    if sub is None:
        raise SubscriptionNotFound()
    return ok(SubscriptionOut.model_validate(sub).model_dump())


@router.get("/users/me/subscription/billing-cycles")
async def list_my_billing_cycles(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Return the authenticated student's billing cycle history, newest first."""
    rows, total = await service.list_my_billing_cycles(db, current_user.id, skip, limit)
    return ok(
        [BillingCycleOut.model_validate(r).model_dump() for r in rows],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@admin_router.get("/subscriptions")
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="Filter by subscription status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all student subscriptions with optional status filter."""
    rows, total = await service.admin_list_subscriptions(
        db,
        status=status,
        skip=skip,
        limit=limit,
    )
    out = [
        AdminSubscriptionOut(
            **{k: v for k, v in row.__dict__.items() if not k.startswith("_")},
            user_email=row.user.email,
        ).model_dump()
        for row in rows
    ]
    return ok(out, meta={"total": total, "skip": skip, "limit": limit})


@admin_router.get("/subscriptions/{subscription_id}")
async def get_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a single subscription by ID."""
    row = await service.admin_get_subscription(db, subscription_id)
    out = AdminSubscriptionOut(
        **{k: v for k, v in row.__dict__.items() if not k.startswith("_")},
        user_email=row.user.email,
    )
    return ok(out.model_dump())


@admin_router.get("/subscriptions/{subscription_id}/billing-cycles")
async def list_subscription_billing_cycles(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List billing cycles for a specific subscription."""
    rows, total = await service.admin_list_billing_cycles(
        db,
        subscription_id,
        skip=skip,
        limit=limit,
    )
    sub = await db.get(Subscription, subscription_id)
    user_id = sub.user_id if sub else None
    out = [
        AdminBillingCycleOut(
            **{k: v for k, v in r.__dict__.items() if not k.startswith("_")},
            user_id=user_id,
        ).model_dump()
        for r in rows
    ]
    return ok(out, meta={"total": total, "skip": skip, "limit": limit})


router.include_router(admin_router)
