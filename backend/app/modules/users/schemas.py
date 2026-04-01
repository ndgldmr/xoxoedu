"""Pydantic request/response schemas for user self-service endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserUpdateIn(BaseModel):
    """Partial update payload for the authenticated user's profile fields."""

    display_name: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=1000)
    headline: str | None = Field(None, max_length=255)
    social_links: dict | None = None
    skills: list[str] | None = None


class SessionOut(BaseModel):
    """Read-only session representation returned by the session list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
