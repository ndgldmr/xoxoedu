"""FastAPI router for Stripe checkout, payment history, and admin payment ops."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service as admin_service
from app.modules.admin.schemas import RefundOut
from app.modules.payments import service
from app.modules.payments.schemas import CheckoutRequest, CheckoutResponse

router = APIRouter(tags=["payments"])
admin_router = APIRouter(prefix="/admin", tags=["payments"], dependencies=[require_role(Role.ADMIN)])


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
    """Receive and process Stripe payment webhook events."""
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


@admin_router.get("/payments")
async def list_payments(
    db: AsyncSession = Depends(get_db),
    course_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all payments across the platform with optional filters."""
    payments, total = await admin_service.list_payments_admin(db, course_id, status, skip, limit)
    return ok(
        [p.model_dump() for p in payments],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@admin_router.post("/payments/{payment_id}/refund")
async def refund_payment(
    payment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a Stripe refund for a completed payment."""
    result = await admin_service.refund_payment(db, payment_id)
    return ok(RefundOut.model_validate(result).model_dump())


router.include_router(admin_router)
