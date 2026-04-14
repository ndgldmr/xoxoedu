"""FastAPI router for AI admin configuration endpoints."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.session import get_db
from app.modules.ai import service
from app.modules.ai.schemas import AIConfigOut, AIConfigUpdate

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get(
    "/admin/ai/config/{course_id}",
    dependencies=[require_role(Role.ADMIN)],
)
async def get_ai_config(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return AI configuration for a course.

    Returns persisted config if it exists, or platform defaults if the course
    has never been configured.  Does not create a row in the database.

    Args:
        course_id: UUID of the course.
        db: Database session.

    Returns:
        ``AIConfigOut`` wrapped in the standard response envelope.
    """
    config = await service.get_ai_config(course_id, db)
    return ok(AIConfigOut.model_validate(config).model_dump())


@router.patch(
    "/admin/ai/config/{course_id}",
    dependencies=[require_role(Role.ADMIN)],
)
async def update_ai_config(
    course_id: uuid.UUID,
    body: AIConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create or update AI configuration for a course.

    Creates a new config row with platform defaults if none exists, then
    applies the supplied partial update.

    Args:
        course_id: UUID of the course to configure.
        body: Fields to update; omitted fields are unchanged.
        db: Database session.

    Returns:
        Updated ``AIConfigOut`` wrapped in the standard response envelope.
    """
    config = await service.update_ai_config(course_id, body, db)
    return ok(AIConfigOut.model_validate(config).model_dump())
