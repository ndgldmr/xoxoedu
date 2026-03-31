import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Category ──────────────────────────────────────────────────────────────────

class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


# ── Lesson Resource ────────────────────────────────────────────────────────────

class ResourceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    file_url: str
    file_type: str | None = None
    size_bytes: int | None = None


class ResourceOut(BaseModel):
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
    title: str | None = Field(None, min_length=1, max_length=255)
    type: LESSON_TYPES | None = None
    content: dict | None = None
    video_asset_id: str | None = None
    is_free_preview: bool | None = None
    is_locked: bool | None = None


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chapter_id: uuid.UUID
    title: str
    type: str
    video_asset_id: str | None
    is_free_preview: bool
    is_locked: bool
    position: int
    created_at: datetime
    resources: list[ResourceOut] = []


# ── Chapter ────────────────────────────────────────────────────────────────────

class ChapterCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChapterUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    position: int
    created_at: datetime


class ChapterDetail(ChapterOut):
    lessons: list[LessonOut] = []


class ReorderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)


# ── Course ─────────────────────────────────────────────────────────────────────

COURSE_LEVELS = Literal["beginner", "intermediate", "advanced"]
COURSE_STATUSES = Literal["draft", "published", "archived"]


class CourseCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=200)
    description: str | None = None
    cover_image_url: str | None = None
    category_id: uuid.UUID | None = None
    level: COURSE_LEVELS = "beginner"
    language: str = Field("en", max_length=10)
    price_cents: int = Field(0, ge=0)
    currency: str = Field("USD", max_length=3)
    settings: dict | None = None
    display_instructor_name: str | None = Field(None, max_length=255)
    display_instructor_bio: str | None = None


class CourseUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=200)
    description: str | None = None
    cover_image_url: str | None = None
    category_id: uuid.UUID | None = None
    level: COURSE_LEVELS | None = None
    language: str | None = Field(None, max_length=10)
    price_cents: int | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=3)
    status: COURSE_STATUSES | None = None
    settings: dict | None = None
    display_instructor_name: str | None = Field(None, max_length=255)
    display_instructor_bio: str | None = None


class CourseListItem(BaseModel):
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
    description: str | None
    settings: dict | None
    display_instructor_name: str | None
    display_instructor_bio: str | None
    chapters: list[ChapterDetail] = []
