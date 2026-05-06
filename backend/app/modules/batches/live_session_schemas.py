"""Pydantic schemas for live session requests and responses."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_iana_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"'{value}' is not a valid IANA timezone name")
    return value


class LiveSessionIn(BaseModel):
    """Request body for creating a new live session."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(..., min_length=1, max_length=64)
    provider: str | None = Field(None, max_length=64)
    join_url: str | None = Field(None, max_length=2048)
    recording_url: str | None = Field(None, max_length=2048)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, v: str) -> str:
        return _validate_iana_timezone(v)

    @model_validator(mode="after")
    def ends_after_starts(self) -> "LiveSessionIn":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class LiveSessionUpdateIn(BaseModel):
    """Request body for updating a live session (all fields optional)."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str | None = Field(None, min_length=1, max_length=64)
    provider: str | None = Field(None, max_length=64)
    join_url: str | None = Field(None, max_length=2048)
    recording_url: str | None = Field(None, max_length=2048)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iana_timezone(v)
        return v


class LiveSessionOut(BaseModel):
    """Full live session representation returned to clients."""

    id: uuid.UUID
    batch_id: uuid.UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    timezone: str
    provider: str | None
    join_url: str | None
    recording_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalendarSessionOut(BaseModel):
    """Minimal session representation for the student calendar feed."""

    id: uuid.UUID
    batch_id: uuid.UUID
    batch_title: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    timezone: str
    provider: str | None
    join_url: str | None
    status: str

    model_config = ConfigDict(from_attributes=True)
