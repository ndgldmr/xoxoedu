"""Pydantic request/response schemas for course, chapter, lesson, and resource endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Category ──────────────────────────────────────────────────────────────────

class CategoryOut(BaseModel):
    """Serialised course category."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


# ── Lesson Resource ────────────────────────────────────────────────────────────

class ResourceCreateIn(BaseModel):
    """Payload for attaching a downloadable resource to a lesson."""

    name: str = Field(min_length=1, max_length=255)
    file_url: str
    file_type: str | None = None
    size_bytes: int | None = None


class ResourceOut(BaseModel):
    """Read-only representation of a ``LessonResource``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lesson_id: uuid.UUID
    name: str
    file_url: str
    file_type: str | None
    size_bytes: int | None
    created_at: datetime


# ── Lesson ─────────────────────────────────────────────────────────────────────

LESSON_TYPES = Literal["video", "text", "quiz", "assignment", "code_exercise", "live_session"]


class LessonCreateIn(BaseModel):
    """Payload for creating a new lesson within a chapter.

    The ``validate_type_fields`` validator enforces that video lessons carry a
    ``video_asset_id`` or ``content`` and that text lessons carry ``content``.
    """

    title: str = Field(min_length=1, max_length=255)
    type: LESSON_TYPES
    content: dict | None = None
    video_asset_id: str | None = None
    is_free_preview: bool = False
    is_locked: bool = False

    @model_validator(mode="after")
    def validate_type_fields(self) -> "LessonCreateIn":
        if self.type == "video" and not self.video_asset_id and not self.content:
            raise ValueError("video lessons require video_asset_id or content")
        if self.type == "text" and not self.content:
            raise ValueError("text lessons require content")
        return self


class LessonUpdateIn(BaseModel):
    """Partial update payload for an existing lesson; ``None`` fields are left unchanged."""

    title: str | None = Field(None, min_length=1, max_length=255)
    type: LESSON_TYPES | None = None
    content: dict | None = None
    video_asset_id: str | None = None
    is_free_preview: bool | None = None
    is_locked: bool | None = None


class LessonOut(BaseModel):
    """Read-only lesson representation returned by listing and detail endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chapter_id: uuid.UUID
    title: str
    type: str
    video_asset_id: str | None
    mux_playback_id: str | None
    is_free_preview: bool
    is_locked: bool
    position: int
    created_at: datetime
    resources: list[ResourceOut] = []


# ── Chapter ────────────────────────────────────────────────────────────────────

class ChapterCreateIn(BaseModel):
    """Payload for creating a new chapter within a course."""

    title: str = Field(min_length=1, max_length=255)


class ChapterUpdateIn(BaseModel):
    """Partial update payload for an existing chapter; ``None`` fields are left unchanged."""

    title: str | None = Field(None, min_length=1, max_length=255)


class ChapterOut(BaseModel):
    """Read-only chapter representation (without lesson detail)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    position: int
    created_at: datetime


class ChapterDetail(ChapterOut):
    """``ChapterOut`` extended with an ordered list of its lessons."""

    lessons: list[LessonOut] = []


class ReorderIn(BaseModel):
    """Payload carrying a complete ordered list of UUIDs for reorder operations."""

    ids: list[uuid.UUID] = Field(min_length=1)


# ── Course ─────────────────────────────────────────────────────────────────────

COURSE_LEVELS = Literal["beginner", "intermediate", "advanced"]
COURSE_STATUSES = Literal["draft", "published", "archived"]


class CourseCreateIn(BaseModel):
    """Payload for creating a new course."""

    title: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=200)
    description: str | None = None
    cover_image_url: str | None = None
    category_id: uuid.UUID | None = Field(None, examples=[None])
    level: COURSE_LEVELS = "beginner"
    language: str = Field("en", max_length=10)
    price_cents: int = Field(0, ge=0)
    currency: str = Field("USD", max_length=3)
    settings: dict | None = Field(None, examples=[None])
    display_instructor_name: str | None = Field(None, max_length=255)
    display_instructor_bio: str | None = None


class CourseUpdateIn(BaseModel):
    """Partial update payload for an existing course; ``None`` fields are left unchanged."""

    title: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=200)
    description: str | None = None
    cover_image_url: str | None = None
    category_id: uuid.UUID | None = Field(None, examples=[None])
    level: COURSE_LEVELS | None = None
    language: str | None = Field(None, max_length=10)
    price_cents: int | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=3)
    status: COURSE_STATUSES | None = None
    settings: dict | None = Field(None, examples=[None])
    display_instructor_name: str | None = Field(None, max_length=255)
    display_instructor_bio: str | None = None


class CourseListItem(BaseModel):
    """Compact course representation returned by list and search endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    cover_image_url: str | None
    category: CategoryOut | None
    level: str
    price_cents: int
    currency: str
    status: str
    created_at: datetime


class CourseDetail(CourseListItem):
    """``CourseListItem`` extended with full description, settings, and chapter tree."""

    description: str | None
    settings: dict | None
    display_instructor_name: str | None
    display_instructor_bio: str | None
    chapters: list[ChapterDetail] = []
