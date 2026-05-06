"""Pydantic schemas for batch, enrollment, and transfer workflows."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── Shared validators ──────────────────────────────────────────────────────────

def _validate_iana_timezone(value: str) -> str:
    """Confirm the string is a recognised IANA timezone name.

    Args:
        value: Candidate timezone string (e.g. ``"America/New_York"``).

    Returns:
        The original value if it is valid.

    Raises:
        ValueError: If the string is not a recognised IANA timezone name.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError) as err:
        raise ValueError(f"'{value}' is not a valid IANA timezone name") from err
    return value


# ── Batch schemas ──────────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[str, set[str]] = {
    "upcoming": {"active", "archived"},
    "active": {"archived"},
    "archived": set(),
}

VALID_TRANSFER_REQUEST_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "denied", "canceled"},
    "approved": set(),
    "denied": set(),
    "canceled": set(),
}


class BatchIn(BaseModel):
    """Request body for creating a new batch."""

    program_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    timezone: str = Field(..., min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    enrollment_opens_at: datetime | None = None
    enrollment_closes_at: datetime | None = None
    capacity: int | None = Field(None, gt=0)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, v: str) -> str:
        return _validate_iana_timezone(v)

    @model_validator(mode="after")
    def ends_after_starts(self) -> "BatchIn":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class BatchUpdateIn(BaseModel):
    """Request body for updating an existing batch (all fields optional)."""

    title: str | None = Field(None, min_length=1, max_length=255)
    timezone: str | None = Field(None, min_length=1, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enrollment_opens_at: datetime | None = None
    enrollment_closes_at: datetime | None = None
    capacity: int | None = Field(None, gt=0)
    status: str | None = None

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iana_timezone(v)
        return v

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_TRANSITIONS:
            raise ValueError(f"status must be one of: {', '.join(VALID_TRANSITIONS)}")
        return v


class BatchOut(BaseModel):
    """Full batch representation returned to clients."""

    id: uuid.UUID
    program_id: uuid.UUID
    title: str
    status: str
    timezone: str
    starts_at: datetime
    ends_at: datetime
    enrollment_opens_at: datetime | None
    enrollment_closes_at: datetime | None
    capacity: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Batch membership schemas ───────────────────────────────────────────────────

class BatchMemberIn(BaseModel):
    """Request body for adding a student to a batch."""

    user_id: uuid.UUID


class MemberUserOut(BaseModel):
    """Minimal user summary embedded in batch member responses."""

    id: uuid.UUID
    email: str
    username: str | None
    display_name: str | None

    model_config = ConfigDict(from_attributes=True)


class BatchMemberOut(BaseModel):
    """Batch enrollment record returned by admin membership endpoints."""

    id: uuid.UUID
    batch_id: uuid.UUID
    program_enrollment_id: uuid.UUID
    enrolled_at: datetime
    user: MemberUserOut

    model_config = ConfigDict(from_attributes=True)


class BatchMembershipOut(BaseModel):
    """Student-facing view of a single batch membership."""

    id: uuid.UUID
    enrolled_at: datetime
    batch: BatchOut

    model_config = ConfigDict(from_attributes=True)


class BatchAvailabilityOut(BaseModel):
    """Student-facing batch availability item with computed remaining seats."""

    id: uuid.UUID
    program_id: uuid.UUID
    title: str
    status: str
    timezone: str
    starts_at: datetime
    ends_at: datetime
    enrollment_opens_at: datetime | None
    enrollment_closes_at: datetime | None
    capacity: int
    remaining_seats: int = Field(..., ge=0)


class BatchSelectionIn(BaseModel):
    """Request body for student self-selection into a batch."""

    batch_id: uuid.UUID


# ── Batch transfer schemas ────────────────────────────────────────────────────

class BatchTransferRequestIn(BaseModel):
    """Request body for a student batch transfer request."""

    to_batch_id: uuid.UUID
    reason: str | None = Field(None, min_length=1, max_length=2000)


class BatchTransferBatchOut(BaseModel):
    """Compact batch summary embedded in transfer responses."""

    id: uuid.UUID
    program_id: uuid.UUID
    title: str
    status: str
    timezone: str
    starts_at: datetime
    ends_at: datetime
    enrollment_opens_at: datetime | None
    enrollment_closes_at: datetime | None
    capacity: int

    model_config = ConfigDict(from_attributes=True)


class BatchTransferReviewerOut(BaseModel):
    """Minimal user summary for transfer review metadata."""

    id: uuid.UUID
    email: str
    username: str | None
    display_name: str | None

    model_config = ConfigDict(from_attributes=True)


class BatchTransferRequestStudentOut(BaseModel):
    """Student-facing transfer request representation."""

    id: uuid.UUID
    status: str
    reason: str | None
    from_batch: BatchTransferBatchOut | None
    to_batch: BatchTransferBatchOut | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchTransferRequestAdminOut(BatchTransferRequestStudentOut):
    """Admin-facing transfer request representation with actor metadata."""

    user: MemberUserOut
    reviewer: BatchTransferReviewerOut | None


# ── Admin reporting schemas (AL-BE-8) ────────────────────────────────────────

class StudentCourseProgressOut(BaseModel):
    """Progress for one student on one program step/course within a batch.

    ``best_quiz_score_pct`` is ``None`` when the course has no quiz or the
    student has not submitted one.  ``latest_assignment_score`` is ``None``
    when the grade has not been published.
    """

    step_position: int
    course_id: uuid.UUID
    course_title: str
    enrollment_status: str | None   # "active" | "completed" | None
    completion_pct: float           # 0.0–1.0 (completed lessons / total lessons)
    best_quiz_score_pct: float | None
    latest_assignment_score: float | None  # published grade_score (0–100) or None


class BatchStudentProgressOut(BaseModel):
    """Progress row for a single student within a batch.

    ``overall_completion_pct`` is the mean ``completion_pct`` across all
    *required* program steps.  Optional steps are excluded from this figure.
    """

    user_id: uuid.UUID
    email: str
    display_name: str | None
    batch_enrolled_at: datetime
    overall_completion_pct: float
    courses: list[StudentCourseProgressOut]
