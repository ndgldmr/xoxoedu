"""Pydantic schemas for admin-only request bodies and responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.rbac import Role


class RoleUpdateIn(BaseModel):
    """Payload for ``PATCH /admin/users/{user_id}/role``."""

    role: Role


# ── Coupons ────────────────────────────────────────────────────────────────────

class CouponCreateIn(BaseModel):
    """Payload for ``POST /admin/coupons``."""

    code: str
    discount_type: str
    discount_value: float
    max_uses: int | None = None
    applies_to: list[uuid.UUID] | None = None
    expires_at: datetime | None = None

    @field_validator("discount_type")
    @classmethod
    def validate_discount_type(cls, v: str) -> str:
        if v not in {"percentage", "fixed"}:
            raise ValueError("discount_type must be 'percentage' or 'fixed'")
        return v

    @field_validator("discount_value")
    @classmethod
    def validate_discount_value(cls, v: float) -> float:
        if v < 0:
            raise ValueError("discount_value must be non-negative")
        return v


class CouponUpdateIn(BaseModel):
    """Payload for ``PATCH /admin/coupons/{id}``."""

    expires_at: datetime | None = None
    max_uses: int | None = None


class CouponOut(BaseModel):
    """Response schema for a coupon."""

    id: uuid.UUID
    code: str
    discount_type: str
    discount_value: float
    max_uses: int | None
    uses_count: int
    applies_to: list[str] | None
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payments ───────────────────────────────────────────────────────────────────

class AdminPaymentOut(BaseModel):
    """Response schema for a payment record in the admin view."""

    id: uuid.UUID
    user_id: uuid.UUID
    course_id: uuid.UUID
    amount_cents: int
    currency: str
    status: str
    provider_payment_id: str | None
    created_at: datetime
    user_email: str | None = None
    course_title: str | None = None

    model_config = {"from_attributes": True}


class RefundOut(BaseModel):
    """Response schema after a successful refund."""

    payment_id: uuid.UUID
    status: str
    stripe_refund_id: str


# ── Grading ────────────────────────────────────────────────────────────────────

class GradeSubmissionIn(BaseModel):
    """Payload for ``PATCH /admin/submissions/{id}/grade``.

    Attributes:
        grade_score: Numeric score in the range 0–100.
        grade_feedback: Written feedback for the student.
        publish: When ``True`` the grade is published immediately and the student
            is notified.  ``False`` saves a draft visible only to admins.
    """

    grade_score: float = Field(ge=0.0, le=100.0)
    grade_feedback: str = Field(min_length=1)
    publish: bool = False


class AdminSubmissionOut(BaseModel):
    """Full submission representation for the admin grading queue.

    Attributes:
        id: Submission UUID.
        assignment_id: The assignment this submission belongs to.
        assignment_title: Display name of the assignment (populated by service).
        lesson_title: Title of the parent lesson (populated by service).
        user_id: The student who submitted.
        user_email: Student's email address (populated by service).
        file_name: Original filename.
        file_size: Declared file size in bytes.
        mime_type: Declared MIME type.
        scan_status: Virus scan state.
        attempt_number: 1-based attempt counter.
        submitted_at: Set when the student confirmed the upload.
        grade_score: Numeric score; ``None`` until graded.
        grade_feedback: Written feedback; ``None`` until graded.
        grade_published_at: ``None`` while draft; timestamp when published.
        graded_by: UUID of the grading admin; ``None`` until graded.
        is_reopened: ``True`` if the admin allowed a resubmission.
        created_at: Row creation timestamp.
    """

    id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str | None = None
    lesson_title: str | None = None
    user_id: uuid.UUID
    user_email: str | None = None
    file_name: str
    file_size: int
    mime_type: str
    scan_status: str
    attempt_number: int
    submitted_at: datetime | None
    grade_score: float | None
    grade_feedback: str | None
    grade_published_at: datetime | None
    graded_by: uuid.UUID | None
    is_reopened: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminSubmissionDetailOut(AdminSubmissionOut):
    """Extended submission representation for the admin grading detail view.

    Extends ``AdminSubmissionOut`` with a short-lived presigned download URL
    so the grader can retrieve the submitted file without a separate backend call.

    Attributes:
        download_url: Presigned R2 GET URL valid for 5 minutes; ``None`` when
            the storage call fails (e.g. in test environments without real R2).
    """

    download_url: str | None = None


# ── Analytics ──────────────────────────────────────────────────────────────────

class LessonDropOffItem(BaseModel):
    """Completion stats for a single lesson, used in the course analytics response."""

    lesson_id: uuid.UUID
    lesson_title: str
    chapter_title: str
    completion_count: int
    completion_rate: float


class CourseAnalyticsOut(BaseModel):
    """Aggregated analytics for a single course."""

    course_id: uuid.UUID
    total_enrollments: int
    active_enrollments: int
    completed_enrollments: int
    completion_rate: float
    average_quiz_score: float | None
    lesson_drop_off: list[LessonDropOffItem]


class StudentProgressRow(BaseModel):
    """One row in the per-course student progress table."""

    user_id: uuid.UUID
    user_email: str
    display_name: str | None
    enrolled_at: datetime
    status: str
    completion_pct: float
    last_active_at: datetime | None


class TopCourseItem(BaseModel):
    """Summary of a course used in the platform analytics response."""

    course_id: uuid.UUID
    title: str
    enrollment_count: int


class PlatformAnalyticsOut(BaseModel):
    """Platform-wide aggregated metrics for the admin dashboard."""

    total_students: int
    active_students_30d: int
    total_enrollments: int
    total_revenue_cents: int
    top_courses: list[TopCourseItem]


# ── Announcements ──────────────────────────────────────────────────────────────

class AnnouncementIn(BaseModel):
    """Payload for ``POST /admin/announcements``.

    Attributes:
        title: Short subject line (≤ 255 chars).
        body: Full announcement text.
        scope: ``"course"`` to target one course; ``"platform"`` for all students.
        course_id: Required when ``scope="course"``; ignored for platform scope.
    """

    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    scope: str
    course_id: uuid.UUID | None = None

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        if v not in {"course", "platform"}:
            raise ValueError("scope must be 'course' or 'platform'")
        return v


class AnnouncementOut(BaseModel):
    """Response schema for an announcement."""

    id: uuid.UUID
    title: str
    body: str
    scope: str
    course_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime
    sent_at: datetime | None

    model_config = {"from_attributes": True}


# ── Content image upload ────────────────────────────────────────────────────────

class ContentImageUploadIn(BaseModel):
    """Payload for ``POST /admin/lessons/{lesson_id}/images/upload-url``."""

    filename: str
    content_type: str


class ContentImageUploadOut(BaseModel):
    """Response schema for a content image upload URL request.

    Attributes:
        upload_url: Presigned R2 PUT URL valid for 5 minutes.  The client
            should PUT the raw file bytes to this URL directly.
        public_url: Permanent public URL to embed in the lesson HTML body.
    """

    upload_url: str
    public_url: str
