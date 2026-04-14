"""Service layer for AI configuration and prompt rendering."""

import os
import uuid

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.ai import AIUsageBudget
from app.modules.ai.schemas import AIConfigUpdate

_prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
_jinja_env = Environment(
    loader=FileSystemLoader(_prompts_dir),
    autoescape=False,
)


def render_prompt(template_name: str, **kwargs: object) -> str:
    """Render a Jinja2 prompt template from the ``prompts/`` directory.

    Args:
        template_name: Filename relative to ``prompts/`` (e.g. ``"base.j2"``).
        **kwargs: Variables injected into the template context.

    Returns:
        The rendered prompt string.
    """
    return _jinja_env.get_template(template_name).render(**kwargs)


async def get_ai_config(course_id: uuid.UUID, db: AsyncSession) -> AIUsageBudget:
    """Return the AI config for a course, or an unsaved default if none exists.

    The returned object may be transient (not yet persisted).  Callers that
    only need to *read* config can use it directly; callers that need to
    *write* should use ``update_ai_config`` instead.

    Args:
        course_id: The course to look up.
        db: Async database session.

    Returns:
        Persisted or default ``AIUsageBudget`` for the course.
    """
    row = await db.scalar(
        select(AIUsageBudget).where(AIUsageBudget.course_id == course_id)
    )
    if row is None:
        return AIUsageBudget(
            course_id=course_id,
            ai_enabled=True,
            tone="encouraging",
            alert_threshold=0.8,
            monthly_token_limit=settings.AI_MONTHLY_TOKEN_BUDGET,
        )
    return row


async def update_ai_config(
    course_id: uuid.UUID, data: AIConfigUpdate, db: AsyncSession
) -> AIUsageBudget:
    """Upsert the AI config for a course and return the updated row.

    Creates a new row with platform defaults if none exists, then applies
    the supplied partial update.

    Args:
        course_id: The course to configure.
        data: Partial update; ``None`` fields are left unchanged.
        db: Async database session.

    Returns:
        The persisted, refreshed ``AIUsageBudget``.
    """
    row = await db.scalar(
        select(AIUsageBudget).where(AIUsageBudget.course_id == course_id)
    )
    if row is None:
        row = AIUsageBudget(
            course_id=course_id,
            monthly_token_limit=settings.AI_MONTHLY_TOKEN_BUDGET,
        )
        db.add(row)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return row
