"""FastAPI router for coupon validation."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.coupons import service
from app.modules.coupons.schemas import CouponValidateRequest, CouponValidateResponse

router = APIRouter(tags=["coupons"])


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
