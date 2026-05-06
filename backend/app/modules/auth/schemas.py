"""Pydantic request/response schemas for authentication endpoints."""

import uuid
from datetime import date, datetime

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.modules.auth.profile import (
    ALLOWED_AVATAR_MIME_TYPES,
    AVATAR_MAX_FILE_SIZE_BYTES,
    SUPPORTED_COUNTRY_NAMES_BY_CODE,
    SUPPORTED_GENDERS,
    SUPPORTED_SOCIAL_LINK_KEYS,
    SUPPORTED_SIGNUP_COUNTRY_CODES,
    is_profile_complete,
)


def _normalize_username(value: str) -> str:
    """Normalize a username before regex validation."""
    return value.strip().lower()


def _normalize_gender_out(value: str | None) -> str | None:
    """Map legacy stored gender values onto the current public enum."""
    if value in {"non_binary", "self_describe"}:
        return "other"
    return value


class SocialLinksIn(BaseModel):
    """Allowed optional social profile URLs for signup/profile completion."""

    linkedin: AnyHttpUrl | None = None
    instagram: AnyHttpUrl | None = None
    tiktok: AnyHttpUrl | None = None
    website: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def collapse_empty_payload(self) -> "SocialLinksIn":
        """Keep OpenAPI explicit while treating all-empty payloads as absent."""
        if not self.model_dump(exclude_none=True):
            return self
        return self


class CountryOptionOut(BaseModel):
    """Selectable country option for registration."""

    code: str
    name: str


class AvatarUploadRequestIn(BaseModel):
    """Anonymous avatar upload-init request for registration."""

    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str
    file_size: int = Field(gt=0, le=AVATAR_MAX_FILE_SIZE_BYTES)

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        if value not in ALLOWED_AVATAR_MIME_TYPES:
            raise ValueError("Avatar must be a JPEG, PNG, or WebP image.")
        return value


class AvatarUploadOut(BaseModel):
    """Presigned avatar-upload response payload."""

    upload_url: str
    public_url: str


class AvatarConstraintsOut(BaseModel):
    """Client-side avatar constraints supplied by the backend."""

    accepted_mime_types: list[str]
    max_file_size_bytes: int


class RegisterOptionsOut(BaseModel):
    """Reference data required to render the WC-03 registration flow."""

    countries: list[CountryOptionOut]
    genders: list[str]
    social_link_keys: list[str]
    avatar_constraints: AvatarConstraintsOut


class UsernameAvailabilityQuery(BaseModel):
    """Query model for the public username-availability endpoint."""

    username: str = Field(min_length=3, max_length=50)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        if isinstance(value, str):
            return _normalize_username(value)
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not value or len(value) < 3 or len(value) > 50 or not value.replace("_", "a").isalnum():
            raise ValueError("Use lowercase letters, numbers, and underscores only.")
        return value


class UsernameAvailabilityOut(BaseModel):
    """Availability state for a candidate username."""

    available: bool
    username: str


class RegisterRequest(BaseModel):
    """Payload for ``POST /auth/register``."""

    email: EmailStr
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    country: str = Field(min_length=2, max_length=2)
    gender: str
    avatar_url: str = Field(min_length=1)
    social_links: SocialLinksIn | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """Normalize signup handles before regex validation."""
        if isinstance(value, str):
            return _normalize_username(value)
        return value

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in SUPPORTED_SIGNUP_COUNTRY_CODES:
            raise ValueError("No subscription plan is available for your country.")
        return value

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, value: str) -> str:
        if value not in SUPPORTED_GENDERS:
            raise ValueError("Select a valid gender option.")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("Date of birth must be in the past.")
        return value


class LoginRequest(BaseModel):
    """Payload for ``POST /auth/login``."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Access-token envelope returned after a successful login or token refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    """Full user representation returned by auth and user-management endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    username: str
    role: str
    email_verified: bool
    created_at: datetime
    display_name: str | None
    avatar_url: str | None
    bio: str | None
    headline: str | None
    social_links: SocialLinksIn | None
    skills: list[str] | None
    date_of_birth: date | None
    country: str | None
    gender: str | None
    gender_self_describe: str | None

    @field_validator("gender", mode="before")
    @classmethod
    def normalize_gender_output(cls, value: str | None) -> str | None:
        return _normalize_gender_out(value)

    @field_validator("gender_self_describe", mode="before")
    @classmethod
    def clear_legacy_gender_self_describe(cls, value: str | None) -> None:
        return None

    @computed_field
    @property
    def profile_complete(self) -> bool:
        return is_profile_complete(self)


class ForgotPasswordRequest(BaseModel):
    """Payload for ``POST /auth/forgot-password``."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Payload for ``POST /auth/reset-password/{token}``."""

    password: str = Field(min_length=8, max_length=128)


def build_register_options() -> RegisterOptionsOut:
    """Return backend-owned WC-03 registration reference data."""
    return RegisterOptionsOut(
        countries=[
            CountryOptionOut(code=code, name=SUPPORTED_COUNTRY_NAMES_BY_CODE[code])
            for code in SUPPORTED_SIGNUP_COUNTRY_CODES
        ],
        genders=list(SUPPORTED_GENDERS),
        social_link_keys=list(SUPPORTED_SOCIAL_LINK_KEYS),
        avatar_constraints=AvatarConstraintsOut(
            accepted_mime_types=list(ALLOWED_AVATAR_MIME_TYPES),
            max_file_size_bytes=AVATAR_MAX_FILE_SIZE_BYTES,
        ),
    )
