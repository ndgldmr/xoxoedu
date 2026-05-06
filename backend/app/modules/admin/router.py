"""FastAPI router for cross-domain admin endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service
from app.modules.admin.schemas import (
    AnnouncementIn,
    AnnouncementOut,
    PlatformAnalyticsOut,
    RoleUpdateIn,
)
from app.modules.auth.schemas import UserOut

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[require_role(Role.ADMIN)])


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all users with pagination metadata."""
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
    """Change the role of a user."""
    user = await service.update_role(db, user_id, body.role.value)
    return ok(UserOut.model_validate(user).model_dump())


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a user account."""
    await service.delete_user(db, user_id)


@router.get("/analytics/platform")
async def get_platform_analytics(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Platform-wide aggregated metrics."""
    result = await service.get_platform_analytics(db)
    return ok(PlatformAnalyticsOut.model_validate(result).model_dump())


@router.post("/announcements", status_code=201)
async def create_announcement(
    data: AnnouncementIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Create an announcement and dispatch emails to targeted students."""
    result = await service.create_announcement(db, current_user.id, data)
    return ok(AnnouncementOut.model_validate(result).model_dump())


@router.get("/announcements")
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all announcements, newest first."""
    announcements, total = await service.list_announcements(db, skip, limit)
    return ok(
        [AnnouncementOut.model_validate(a).model_dump() for a in announcements],
        meta={"total": total, "skip": skip, "limit": limit},
    )
