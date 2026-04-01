"""Pydantic request/response schemas for enrollment, progress, notes, and bookmark endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROGRESS_STATUS = Literal["not_started", "in_progress", "completed"]
ENROLLMENT_STATUS = Literal["active", "unenrolled", "completed"]


# ── Shared refs ────────────────────────────────────────────────────────────────

class CourseRef(BaseModel):
    """Minimal course snapshot embedded in enrollment and continue-learning responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    cover_image_url: str | None


class LessonRef(BaseModel):
    """Minimal lesson snapshot embedded in bookmark list items."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str


class ChapterRef(BaseModel):
    """Minimal chapter snapshot with nested course reference for bookmark context."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    course: CourseRef


class LessonWithChapterRef(BaseModel):
    """Lesson snapshot with its parent chapter (and grandparent course) for bookmark list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    chapter: ChapterRef


# ── Enrollment ─────────────────────────────────────────────────────────────────

class EnrollmentOut(BaseModel):
    """Full enrollment record with a nested course summary.

    Attributes:
        id: Enrollment primary key.
        course_id: FK to the enrolled course.
        course: Minimal course snapshot (title, slug, cover).
        status: Current enrollment state.
        enrolled_at: Timestamp of initial enrollment.
        completed_at: Set when all course lessons are completed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    course: CourseRef
    status: ENROLLMENT_STATUS
    enrolled_at: datetime
    completed_at: datetime | None


# ── Progress ───────────────────────────────────────────────────────────────────

class LessonProgressIn(BaseModel):
    """Payload for saving or updating lesson progress.

    Attributes:
        status: Target progress state; transitions are forward-only.
        watch_seconds: Current video playback position in seconds.
    """

    status: PROGRESS_STATUS
    watch_seconds: int | None = Field(None, ge=0)


class LessonProgressOut(BaseModel):
    """Progress record for a single lesson.

    Attributes:
        lesson_id: The lesson this record belongs to.
        status: Current progress state.
        watch_seconds: Accumulated seconds watched.
        completed_at: Set when ``status`` first became ``"completed"``.
        updated_at: Last modified timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    lesson_id: uuid.UUID
    status: str
    watch_seconds: int
    completed_at: datetime | None
    updated_at: datetime


class LessonProgressDetail(BaseModel):
    """Per-lesson breakdown used inside ``CourseProgressOut``.

    Attributes:
        lesson_id: The lesson this record describes.
        lesson_title: Display title of the lesson.
        status: Current progress state (defaults to ``"not_started"`` if no record).
        watch_seconds: Accumulated seconds watched.
        completed_at: Set when the lesson was completed.
    """

    lesson_id: uuid.UUID
    lesson_title: str
    status: str
    watch_seconds: int
    completed_at: datetime | None


class CourseProgressOut(BaseModel):
    """Aggregated course-level progress with per-lesson breakdown.

    Attributes:
        course_id: The course this progress summary belongs to.
        total_lessons: Total number of lessons in the course.
        completed_lessons: Number of lessons with status ``"completed"``.
        progress_pct: Percentage of lessons completed, rounded to one decimal.
        lessons: Ordered list of per-lesson progress details.
    """

    course_id: uuid.UUID
    total_lessons: int
    completed_lessons: int
    progress_pct: float
    lessons: list[LessonProgressDetail]


class ContinueLearningItem(BaseModel):
    """Next incomplete lesson for a single enrolled course.

    Attributes:
        course_id: The enrolled course.
        course_title: Display title of the course.
        course_slug: URL slug of the course.
        next_lesson_id: Primary key of the first incomplete lesson.
        next_lesson_title: Display title of that lesson.
    """

    course_id: uuid.UUID
    course_title: str
    course_slug: str
    next_lesson_id: uuid.UUID
    next_lesson_title: str


# ── Notes ──────────────────────────────────────────────────────────────────────

class NoteIn(BaseModel):
    """Payload for creating or updating a lesson note.

    Attributes:
        content: Note body text; must be at least one character.
    """

    content: str = Field(min_length=1)


class NoteOut(BaseModel):
    """Serialised lesson note.

    Attributes:
        id: Note primary key.
        lesson_id: The lesson this note is attached to.
        content: Note body text.
        created_at: When the note was first created.
        updated_at: When the note was last modified.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lesson_id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime


# ── Bookmarks ──────────────────────────────────────────────────────────────────

class BookmarkToggleOut(BaseModel):
    """Response for a bookmark toggle indicating the resulting state.

    Attributes:
        bookmarked: ``True`` if the lesson is now bookmarked; ``False`` if removed.
    """

    bookmarked: bool


class BookmarkListItem(BaseModel):
    """A bookmarked lesson with its chapter and course context.

    Attributes:
        id: Bookmark primary key.
        lesson_id: FK to the bookmarked lesson.
        lesson: Lesson snapshot including its parent chapter and course.
        created_at: When the bookmark was created.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lesson_id: uuid.UUID
    lesson: LessonWithChapterRef
    created_at: datetime
