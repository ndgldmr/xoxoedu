import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.session import get_db
from app.modules.admin import service
from app.modules.admin.schemas import RoleUpdateIn
from app.modules.auth.schemas import UserOut

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[require_role(Role.ADMIN)])


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    users, total = await service.list_users(db, skip, limit)
    return ok(
        [UserOut.model_validate(u).model_dump() for u in users],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await service.update_role(db, user_id, body.role.value)
    return ok(UserOut.model_validate(user).model_dump())


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_user(db, user_id)
