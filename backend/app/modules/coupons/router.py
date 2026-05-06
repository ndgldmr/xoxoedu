"""FastAPI router for coupon validation and admin coupon management."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service as admin_service
from app.modules.admin.schemas import CouponCreateIn, CouponOut, CouponUpdateIn
from app.modules.coupons import service
from app.modules.coupons.schemas import CouponValidateRequest, CouponValidateResponse

router = APIRouter(tags=["coupons"])
admin_router = APIRouter(prefix="/admin", tags=["coupons"], dependencies=[require_role(Role.ADMIN)])


@router.post("/coupons/validate", response_model=None)
async def validate_coupon(
    body: CouponValidateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Validate a coupon code and return the applicable discount."""
    result = await service.validate_coupon(
        db, body.code, body.course_id, body.original_amount_cents
    )
    return ok(CouponValidateResponse.model_validate(result).model_dump())


@admin_router.post("/coupons", status_code=201)
async def create_coupon(
    data: CouponCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a discount coupon."""
    coupon = await admin_service.create_coupon(db, data)
    return ok(CouponOut.model_validate(coupon).model_dump())


@admin_router.get("/coupons")
async def list_coupons(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all coupons with usage stats."""
    coupons, total = await admin_service.list_coupons(db, skip, limit)
    return ok(
        [CouponOut.model_validate(c).model_dump() for c in coupons],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@admin_router.patch("/coupons/{coupon_id}")
async def update_coupon(
    coupon_id: uuid.UUID,
    data: CouponUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a coupon's expiry date and or usage cap."""
    coupon = await admin_service.update_coupon(db, coupon_id, data)
    return ok(CouponOut.model_validate(coupon).model_dump())


@admin_router.delete("/coupons/{coupon_id}", status_code=204)
async def delete_coupon(
    coupon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a coupon."""
    await admin_service.delete_coupon(db, coupon_id)


router.include_router(admin_router)
