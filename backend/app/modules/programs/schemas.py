"""Pydantic schemas for program, program-step, and program-enrollment endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Enrollment status lifecycle ────────────────────────────────────────────────

VALID_ENROLLMENT_TRANSITIONS: dict[str, set[str]] = {
    "active":    {"suspended", "completed", "canceled"},
    "suspended": {"active", "canceled"},
    "completed": {"canceled"},
    "canceled":  set(),
}


# ── Program schemas ────────────────────────────────────────────────────────────

class ProgramIn(BaseModel):
    """Request body for creating a new program."""

    code: str = Field(..., min_length=1, max_length=10)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    marketing_summary: str | None = None
    cover_image_url: str | None = None
    display_order: int = Field(0, ge=0)
    is_active: bool = True


class ProgramUpdateIn(BaseModel):
    """Request body for updating an existing program (all fields optional)."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    marketing_summary: str | None = None
    cover_image_url: str | None = None
    display_order: int | None = Field(None, ge=0)
    is_active: bool | None = None


class ProgramOut(BaseModel):
    """Program representation returned to clients."""

    id: uuid.UUID
    code: str
    title: str
    description: str | None
    marketing_summary: str | None
    cover_image_url: str | None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── ProgramStep schemas ────────────────────────────────────────────────────────

class ProgramStepIn(BaseModel):
    """Request body for adding a step to a program."""

    course_id: uuid.UUID
    position: int = Field(..., ge=1)
    is_required: bool = True


class ProgramStepUpdateIn(BaseModel):
    """Request body for updating a program step (all fields optional)."""

    course_id: uuid.UUID | None = None
    position: int | None = Field(None, ge=1)
    is_required: bool | None = None


class ProgramStepReorderIn(BaseModel):
    """Request body for reordering all steps in a program.

    ``step_ids`` must contain exactly the IDs of every existing step in the
    desired new order.  Position values are assigned 1..N from this order.
    """

    step_ids: list[uuid.UUID] = Field(..., min_length=1)


class ProgramStepOut(BaseModel):
    """Program step representation returned to clients."""

    id: uuid.UUID
    program_id: uuid.UUID
    course_id: uuid.UUID
    position: int
    is_required: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProgramWithStepsOut(ProgramOut):
    """Program representation including ordered curriculum steps."""

    steps: list[ProgramStepOut] = []


class PublicProgramStepOut(BaseModel):
    """Public-facing preview of one ordered program step."""

    course_cover_image_url: str | None
    course_id: uuid.UUID
    course_level: str
    course_slug: str
    course_title: str
    is_required: bool
    position: int


class PublicProgramOut(ProgramOut):
    """Public-facing program payload with ordered course previews."""

    steps: list[PublicProgramStepOut] = []


# ── ProgramEnrollment schemas ──────────────────────────────────────────────────

class ProgramEnrollmentAdminIn(BaseModel):
    """Request body for admin-created program enrollment."""

    program_id: uuid.UUID


class ProgramEnrollmentUpdateIn(BaseModel):
    """Request body for updating enrollment status."""

    status: str

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, v: str) -> str:
        if v not in VALID_ENROLLMENT_TRANSITIONS:
            raise ValueError(
                f"status must be one of: {', '.join(VALID_ENROLLMENT_TRANSITIONS)}"
            )
        return v


class ProgramEnrollmentOut(BaseModel):
    """Program enrollment representation returned to clients."""

    id: uuid.UUID
    user_id: uuid.UUID
    program_id: uuid.UUID
    status: str
    enrolled_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


# ── Program progress schemas (AL-BE-7) ────────────────────────────────────────

class AccessibleLessonOut(BaseModel):
    """A single lesson in the current step with its computed unlock state."""

    lesson_id: uuid.UUID
    lesson_title: str
    chapter_id: uuid.UUID
    chapter_title: str
    position_in_course: int    # 0-based flat index across all chapters/lessons
    is_accessible: bool
    is_admin_locked: bool      # mirrors Lesson.is_locked
    progress_status: str       # "not_started" | "in_progress" | "completed"
    completed_at: datetime | None


class CurrentStepOut(BaseModel):
    """The single unlocked step the student is currently working through."""

    step_id: uuid.UUID
    step_position: int
    course_id: uuid.UUID
    course_title: str
    course_slug: str
    enrollment_status: str     # "active" | "completed"
    lessons: list[AccessibleLessonOut]


class ProgramProgressOut(BaseModel):
    """Full dashboard payload for a student's program progression state.

    ``current_step`` is ``None`` only when all steps have been completed and
    the program is finished.
    """

    program_enrollment_id: uuid.UUID
    program_id: uuid.UUID
    program_title: str
    total_steps: int
    completed_steps: int
    current_step: CurrentStepOut | None


# ── Admin reporting schemas (AL-BE-8) ────────────────────────────────────────

class ProgramStudentOut(BaseModel):
    """One row in the admin program student roster report.

    All batch and subscription fields are ``None`` when the student has no
    batch assignment or no subscription record, respectively.
    """

    user_id: uuid.UUID
    email: str
    display_name: str | None
    username: str | None
    enrollment_id: uuid.UUID
    enrollment_status: str          # "active" | "suspended" | "completed" | "canceled"
    enrolled_at: datetime
    completed_at: datetime | None
    batch_id: uuid.UUID | None      # None when the student has no batch assignment
    batch_title: str | None
    subscription_status: str | None  # None when no Subscription row exists
