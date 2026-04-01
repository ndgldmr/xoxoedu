"""Pydantic request/response schemas for authentication endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Payload for ``POST /auth/register``."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    """Payload for ``POST /auth/login``."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Access-token envelope returned after a successful login or token refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ProfileOut(BaseModel):
    """Serialised ``UserProfile`` fields returned within ``UserOut``."""

    model_config = ConfigDict(from_attributes=True)

    display_name: str | None
    avatar_url: str | None
    bio: str | None
    headline: str | None
    social_links: dict | None
    skills: list[str] | None


class UserOut(BaseModel):
    """Full user representation returned by auth and user-management endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    email_verified: bool
    created_at: datetime
    profile: ProfileOut | None


class ForgotPasswordRequest(BaseModel):
    """Payload for ``POST /auth/forgot-password``."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Payload for ``POST /auth/reset-password/{token}``."""

    password: str = Field(min_length=8, max_length=128)
