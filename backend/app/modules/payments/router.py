"""FastAPI router for Stripe Checkout and payment history."""

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.payments import service
from app.modules.payments.schemas import CheckoutRequest, CheckoutResponse

router = APIRouter(tags=["payments"])


@router.post("/payments/checkout", status_code=201)
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Initiate a Stripe Checkout session for a paid course."""
    result = await service.create_checkout_session(
        db, current_user.id, body.course_id, body.coupon_code
    )
    return ok(CheckoutResponse.model_validate(result).model_dump())


@router.post("/payments/webhook", status_code=200)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str = Header(alias="stripe-signature"),
) -> dict:
    """Receive and process Stripe webhook events.

    No JWT auth — Stripe calls this directly.  Signature is verified via
    ``STRIPE_WEBHOOK_SECRET`` before any processing occurs.
    """
    payload = await request.body()
    result = await service.handle_webhook(db, payload, stripe_signature)
    return result


@router.get("/users/me/payments")
async def list_my_payments(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the authenticated student's payment history."""
    payments = await service.list_payments(db, current_user.id)
    return ok([p.model_dump() for p in payments])
