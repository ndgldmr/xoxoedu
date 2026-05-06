"""Pydantic request/response schemas for user self-service endpoints."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.profile import SUPPORTED_GENDERS, SUPPORTED_SIGNUP_COUNTRY_CODES
from app.modules.auth.schemas import SocialLinksIn


class UserUpdateIn(BaseModel):
    """Partial update payload for the authenticated user's profile fields."""

    username: str | None = Field(None, min_length=3, max_length=50, pattern=r"^[a-z0-9_]+$")
    display_name: str | None = Field(None, max_length=100)
    avatar_url: str | None = Field(None, min_length=1)
    date_of_birth: date | None = None
    country: str | None = Field(None, min_length=2, max_length=2)
    gender: str | None = None
    bio: str | None = Field(None, max_length=1000)
    headline: str | None = Field(None, max_length=255)
    social_links: SocialLinksIn | None = None
    skills: list[str] | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if value not in SUPPORTED_SIGNUP_COUNTRY_CODES:
            raise ValueError("No subscription plan is available for your country.")
        return value

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in SUPPORTED_GENDERS:
            raise ValueError("Select a valid gender option.")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is None:
            return value
        if value >= date.today():
            raise ValueError("Date of birth must be in the past.")
        return value


class SessionOut(BaseModel):
    """Read-only session representation returned by the session list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
