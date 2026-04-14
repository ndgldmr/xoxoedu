"""Pydantic schemas for AI config endpoints."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AIConfigOut(BaseModel):
    """Response schema for an AI configuration resource.

    Attributes:
        course_id: The course this config applies to.
        ai_enabled: Whether AI features are active for this course.
        tone: Feedback tone injected into the system prompt.
        system_prompt_override: Full system prompt replacement, if set.
        monthly_token_limit: Hard monthly token cap for this course.
        alert_threshold: Fraction of limit that triggers an admin alert.
    """

    model_config = ConfigDict(from_attributes=True)

    course_id: uuid.UUID
    ai_enabled: bool
    tone: str
    system_prompt_override: str | None
    monthly_token_limit: int
    alert_threshold: float


class AIConfigUpdate(BaseModel):
    """Request body for ``PATCH /admin/ai/config/{course_id}``.

    All fields are optional; only supplied fields are updated.
    """

    ai_enabled: bool | None = None
    tone: Literal["encouraging", "neutral", "strict"] | None = None
    system_prompt_override: str | None = None
    monthly_token_limit: int | None = Field(default=None, ge=1)
    alert_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
