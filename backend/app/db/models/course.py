"""ORM models for the course content hierarchy: Category → Course → Chapter → Lesson → LessonResource."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class Category(Base, UUIDMixin):
    """Course category with optional self-referential nesting.

    Attributes:
        name: Display name shown in the UI.
        slug: URL-safe unique identifier derived from ``name``.
        parent_id: Optional FK to another ``Category`` for sub-categories;
            set to ``NULL`` on parent delete.
        courses: All courses assigned to this category.
    """

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    courses: Mapped[list[Course]] = relationship("Course", back_populates="category")


class Course(Base, UUIDMixin, TimestampMixin):
    """Top-level course record.

    Prices are stored as integer cents to avoid floating-point precision issues
    and to mirror the Stripe API convention.  The ``search_vector`` column is a
    PostgreSQL ``GENERATED ALWAYS AS STORED`` tsvector computed from the title
    and description; the ORM never writes to it.

    Attributes:
        slug: Unique URL-safe identifier; immutable once the course is published.
        title: Course display title.
        description: Optional long-form description.
        cover_image_url: URL of the course thumbnail image.
        category_id: Optional FK to ``categories.id``; set to ``NULL`` on delete.
        level: Difficulty level (``"beginner"``, ``"intermediate"``, or ``"advanced"``).
        language: ISO 639-1 language code (e.g. ``"en"``).
        price_cents: Price in the smallest currency unit (e.g. US cents).
        currency: ISO 4217 currency code (e.g. ``"USD"``).
        status: Publication state (``"draft"``, ``"published"``, or ``"archived"``).
        settings: JSONB blob for arbitrary instructor-defined course settings.
        display_instructor_name: Overridable instructor name shown to learners.
        display_instructor_bio: Overridable instructor biography shown to learners.
        created_by: FK to the ``users.id`` of the admin who created this course.
        archived_at: Set when the course is archived; also used to filter from listings.
        search_vector: Server-generated tsvector for full-text search ranking.
        category: Eager-loadable ``Category`` relationship.
        creator: The creating ``User`` record.
        chapters: Ordered list of ``Chapter`` objects.
    """

    __tablename__ = "courses"

    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="beginner")
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    display_instructor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_instructor_bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))",
            persisted=True,
        ),
        nullable=True,
    )

    category: Mapped[Category | None] = relationship("Category", back_populates="courses")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    chapters: Mapped[list[Chapter]] = relationship(
        "Chapter", back_populates="course", order_by="Chapter.position"
    )


class Chapter(Base, UUIDMixin, TimestampMixin):
    """Ordered section within a course, containing one or more lessons.

    Attributes:
        course_id: FK to the parent ``courses.id``; cascades on delete.
        title: Chapter display title.
        position: 1-based display order within the parent course.
        course: Back-reference to the parent ``Course``.
        lessons: Ordered list of ``Lesson`` objects in this chapter.
    """

    __tablename__ = "chapters"

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    course: Mapped[Course] = relationship("Course", back_populates="chapters")
    lessons: Mapped[list[Lesson]] = relationship(
        "Lesson", back_populates="chapter", order_by="Lesson.position"
    )


class Lesson(Base, UUIDMixin, TimestampMixin):
    """Individual learning unit within a chapter.

    Attributes:
        chapter_id: FK to the parent ``chapters.id``; cascades on delete.
        title: Lesson display title.
        type: Content type (``"video"``, ``"text"``, ``"quiz"``,
            ``"assignment"``, ``"code_exercise"``, or ``"live_session"``).
        content: JSONB payload whose schema varies by ``type`` (e.g. HTML body
            for text lessons, question list for quizzes).
        video_asset_id: Reference to an external video asset (e.g. Mux asset ID).
        is_free_preview: Whether unenrolled users can access this lesson.
        is_locked: Whether the lesson is temporarily hidden from enrolled users.
        position: 1-based display order within the parent chapter.
        chapter: Back-reference to the parent ``Chapter``.
        resources: Downloadable files attached to this lesson.
    """

    __tablename__ = "lessons"

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    video_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mux_playback_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_free_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    chapter: Mapped[Chapter] = relationship("Chapter", back_populates="lessons")
    resources: Mapped[list[LessonResource]] = relationship(
        "LessonResource", back_populates="lesson", cascade="all, delete-orphan"
    )
    transcript: Mapped[LessonTranscript | None] = relationship(
        "LessonTranscript", back_populates="lesson", uselist=False, cascade="all, delete-orphan"
    )


class LessonResource(Base, UUIDMixin):
    """Downloadable file or link attached to a lesson.

    Attributes:
        lesson_id: FK to the parent ``lessons.id``; cascades on delete.
        name: Display name of the resource (e.g. ``"Cheatsheet.pdf"``).
        file_url: Public URL where the file can be downloaded.
        file_type: MIME type or informal type label (e.g. ``"application/pdf"``).
        size_bytes: File size in bytes, used for display purposes.
        created_at: Timestamp set by the database on INSERT.
        lesson: Back-reference to the parent ``Lesson``.
    """

    __tablename__ = "lesson_resources"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    lesson: Mapped[Lesson] = relationship("Lesson", back_populates="resources")


class LessonTranscript(Base, UUIDMixin):
    """Auto-generated (and admin-editable) transcript for a video lesson.

    Created by the ``generate_transcript`` Celery task after Mux signals that
    a video is ready.  One row per lesson (enforced by the unique constraint on
    ``lesson_id``).

    Attributes:
        lesson_id: FK to the parent ``lessons.id``; cascades on delete.
        vtt_key: R2 object key for the WebVTT caption file.
        plain_text: Full transcript as plain text; used for RAG indexing in Sprint 8B.
        created_at: Row creation timestamp.
        updated_at: Last-edited timestamp; set on admin PATCH.
        lesson: Back-reference to the parent ``Lesson``.
    """

    __tablename__ = "lesson_transcripts"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    vtt_key: Mapped[str] = mapped_column(String(512), nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    lesson: Mapped[Lesson] = relationship("Lesson", back_populates="transcript")
