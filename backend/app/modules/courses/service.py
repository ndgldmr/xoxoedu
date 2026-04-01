import uuid
from datetime import UTC, datetime

from slugify import slugify
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    CategoryNotFound,
    ChapterNotFound,
    CourseNotFound,
    InvalidChapterIds,
    InvalidLessonIds,
    InvalidStatusTransition,
    LessonNotFound,
    SlugConflict,
    SlugImmutable,
)
from app.db.models.course import Category, Chapter, Course, Lesson, LessonResource
from app.modules.courses.schemas import (
    ChapterCreateIn,
    ChapterUpdateIn,
    CourseCreateIn,
    CourseUpdateIn,
    LessonCreateIn,
    LessonUpdateIn,
    ResourceCreateIn,
)

# ── Status transition map ──────────────────────────────────────────────────────

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"published", "archived"},
    "published": {"draft", "archived"},
    "archived": {"published"},
}


# ── Categories ─────────────────────────────────────────────────────────────────

async def list_categories(db: AsyncSession) -> list[Category]:
    """Return all course categories ordered alphabetically by name.

    Args:
        db: Async database session.

    Returns:
        A list of ``Category`` ORM instances.
    """
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def create_category(db: AsyncSession, name: str) -> Category:
    """Create a new course category with an auto-generated slug.

    Args:
        db: Async database session.
        name: Human-readable category name (e.g. ``"Web Development"``).

    Returns:
        The newly created ``Category`` ORM instance.
    """
    slug = slugify(name)
    category = Category(name=name, slug=slug)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


# ── Courses ────────────────────────────────────────────────────────────────────

async def _generate_unique_slug(db: AsyncSession, base: str) -> str:
    """Derive a URL-safe slug from *base*, appending a random suffix on collision.

    Makes up to 3 attempts before raising ``SlugConflict``.

    Args:
        db: Async database session.
        base: Source string to slugify (typically the course title).

    Returns:
        A unique slug string not yet present in the ``courses`` table.

    Raises:
        SlugConflict: If all 3 candidate slugs are already taken.
    """
    slug = slugify(base)
    for attempt in range(3):
        candidate = slug if attempt == 0 else f"{slug}-{uuid.uuid4().hex[:8]}"
        existing = await db.scalar(select(Course).where(Course.slug == candidate))
        if not existing:
            return candidate
    raise SlugConflict()


async def create_course(
    db: AsyncSession, body: CourseCreateIn, created_by: uuid.UUID
) -> Course:
    """Create a new course in ``draft`` status.

    If ``body.slug`` is omitted, a unique slug is auto-generated from the title.
    The returned course is fully hydrated with its category and (empty) chapter tree.

    Args:
        db: Async database session.
        body: Validated creation payload.
        created_by: UUID of the admin or instructor creating the course.

    Returns:
        The newly created ``Course`` ORM instance with related data loaded.

    Raises:
        SlugConflict: If the requested slug (or all auto-generated candidates) already exist.
        CategoryNotFound: If ``body.category_id`` references a non-existent category.
    """
    slug = body.slug or await _generate_unique_slug(db, body.title)
    course = Course(
        slug=slug,
        title=body.title,
        description=body.description,
        cover_image_url=body.cover_image_url,
        category_id=body.category_id,
        level=body.level,
        language=body.language,
        price_cents=body.price_cents,
        currency=body.currency,
        settings=body.settings,
        display_instructor_name=body.display_instructor_name,
        display_instructor_bio=body.display_instructor_bio,
        created_by=created_by,
    )
    db.add(course)
    try:
        await db.commit()
    except IntegrityError as err:
        await db.rollback()
        sqlstate = getattr(err.orig, "sqlstate", None)
        if sqlstate == "23505":
            raise SlugConflict() from err
        if sqlstate == "23503":
            raise CategoryNotFound() from err
        raise
    return await get_course_by_id(db, course.id)


async def list_courses(
    db: AsyncSession,
    category_id: uuid.UUID | None,
    level: str | None,
    max_price: int | None,
    skip: int,
    limit: int,
) -> tuple[list[Course], int]:
    """Return a paginated list of published, non-archived courses with optional filters.

    Args:
        db: Async database session.
        category_id: Optional UUID to restrict results to a single category.
        level: Optional difficulty level filter (``"beginner"``, ``"intermediate"``,
            or ``"advanced"``).
        max_price: Optional upper bound on ``price_cents`` (inclusive).
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(courses, total)`` where ``total`` is the unfiltered count of
        matching published courses.
    """
    base = select(Course).where(Course.status == "published", Course.archived_at.is_(None))
    if category_id:
        base = base.where(Course.category_id == category_id)
    if level:
        base = base.where(Course.level == level)
    if max_price is not None:
        base = base.where(Course.price_cents <= max_price)

    count = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.execute(
        base.options(selectinload(Course.category))
        .order_by(Course.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), count or 0


async def get_course_by_slug(db: AsyncSession, slug: str) -> Course:
    """Fetch a published, non-archived course by its URL slug, with full content tree.

    Args:
        db: Async database session.
        slug: The URL-safe course identifier.

    Returns:
        The ``Course`` ORM instance with category, chapters, lessons, and resources loaded.

    Raises:
        CourseNotFound: If no published, non-archived course matches the slug.
    """
    course = await db.scalar(
        select(Course)
        .where(Course.slug == slug, Course.status == "published", Course.archived_at.is_(None))
        .options(
            selectinload(Course.category),
            selectinload(Course.chapters)
            .selectinload(Chapter.lessons)
            .selectinload(Lesson.resources),
        )
    )
    if not course:
        raise CourseNotFound()
    return course


async def get_course_by_id(db: AsyncSession, course_id: uuid.UUID) -> Course:
    """Fetch any course by primary key with full content tree, regardless of status.

    Used internally by write operations that need to return the updated course.

    Args:
        db: Async database session.
        course_id: UUID of the course to load.

    Returns:
        The ``Course`` ORM instance with category, chapters, lessons, and resources loaded.

    Raises:
        CourseNotFound: If no course with that ID exists.
    """
    course = await db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.category),
            selectinload(Course.chapters)
            .selectinload(Chapter.lessons)
            .selectinload(Lesson.resources),
        )
    )
    if not course:
        raise CourseNotFound()
    return course


async def update_course(
    db: AsyncSession, course_id: uuid.UUID, body: CourseUpdateIn
) -> Course:
    """Update course metadata or status, enforcing transition and slug-immutability rules.

    Only non-``None`` fields in *body* are applied.  Status changes are validated
    against ``_ALLOWED_TRANSITIONS``; slugs may not be changed once a course is
    published.

    Args:
        db: Async database session.
        course_id: UUID of the course to update.
        body: Partial update payload.

    Returns:
        The refreshed ``Course`` ORM instance with full content tree.

    Raises:
        CourseNotFound: If the course does not exist.
        InvalidStatusTransition: If the requested status change is not permitted.
        SlugImmutable: If attempting to change the slug of a published course.
        SlugConflict: If the new slug is already taken by another course.
        CategoryNotFound: If the new ``category_id`` references a non-existent category.
    """
    course = await get_course_by_id(db, course_id)

    if body.status and body.status != course.status:
        allowed = _ALLOWED_TRANSITIONS.get(course.status, set())
        if body.status not in allowed:
            raise InvalidStatusTransition()

    if body.slug and body.slug != course.slug and course.status == "published":
        raise SlugImmutable()

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(course, field, value)

    try:
        await db.commit()
    except IntegrityError as err:
        await db.rollback()
        sqlstate = getattr(err.orig, "sqlstate", None)
        if sqlstate == "23505":
            raise SlugConflict() from err
        if sqlstate == "23503":
            raise CategoryNotFound() from err
        raise

    return await get_course_by_id(db, course_id)


async def archive_course(db: AsyncSession, course_id: uuid.UUID) -> None:
    """Set a course's status to ``archived`` and record the archive timestamp.

    Args:
        db: Async database session.
        course_id: UUID of the course to archive.

    Raises:
        CourseNotFound: If the course does not exist.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise CourseNotFound()
    course.status = "archived"
    course.archived_at = datetime.now(UTC)
    await db.commit()


# ── Chapters ───────────────────────────────────────────────────────────────────

async def create_chapter(
    db: AsyncSession, course_id: uuid.UUID, body: ChapterCreateIn
) -> Chapter:
    """Append a new chapter to a course, auto-assigning the next sequential position.

    Args:
        db: Async database session.
        course_id: UUID of the parent course.
        body: Chapter creation payload containing the title.

    Returns:
        The newly created ``Chapter`` ORM instance.

    Raises:
        CourseNotFound: If the course does not exist.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise CourseNotFound()
    max_pos = await db.scalar(
        select(func.max(Chapter.position)).where(Chapter.course_id == course_id)
    )
    chapter = Chapter(
        course_id=course_id,
        title=body.title,
        position=(max_pos or 0) + 1,
    )
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def update_chapter(
    db: AsyncSession, chapter_id: uuid.UUID, body: ChapterUpdateIn
) -> Chapter:
    """Update a chapter's title.

    Args:
        db: Async database session.
        chapter_id: UUID of the chapter to update.
        body: Partial update payload; ``None`` fields are left unchanged.

    Returns:
        The refreshed ``Chapter`` ORM instance.

    Raises:
        ChapterNotFound: If the chapter does not exist.
    """
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise ChapterNotFound()
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(chapter, field, value)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def delete_chapter(db: AsyncSession, chapter_id: uuid.UUID) -> None:
    """Delete a chapter and cascade-delete its lessons and resources.

    Args:
        db: Async database session.
        chapter_id: UUID of the chapter to delete.

    Raises:
        ChapterNotFound: If the chapter does not exist.
    """
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise ChapterNotFound()
    await db.delete(chapter)
    await db.commit()


async def reorder_chapters(
    db: AsyncSession, course_id: uuid.UUID, chapter_ids: list[uuid.UUID]
) -> list[Chapter]:
    """Reorder a course's chapters by assigning positions from the supplied ID list.

    The caller must provide *all* chapter IDs belonging to the course — omitting
    or adding extra IDs raises ``InvalidChapterIds``.

    Args:
        db: Async database session.
        course_id: UUID of the parent course.
        chapter_ids: Complete ordered list of chapter UUIDs.

    Returns:
        All chapters for the course ordered by their new positions.

    Raises:
        InvalidChapterIds: If the supplied IDs do not exactly match the course's chapters.
    """
    result = await db.execute(select(Chapter).where(Chapter.course_id == course_id))
    existing = list(result.scalars().all())
    if set(chapter_ids) != {c.id for c in existing}:
        raise InvalidChapterIds()
    for i, cid in enumerate(chapter_ids, start=1):
        await db.execute(
            update(Chapter)
            .where(Chapter.id == cid, Chapter.course_id == course_id)
            .values(position=i)
        )
    await db.commit()
    result = await db.execute(
        select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.position)
    )
    return list(result.scalars().all())


# ── Lessons ────────────────────────────────────────────────────────────────────

async def _get_lesson(db: AsyncSession, lesson_id: uuid.UUID) -> Lesson:
    """Fetch a lesson by primary key with its resources eagerly loaded.

    Args:
        db: Async database session.
        lesson_id: UUID of the lesson to load.

    Returns:
        The ``Lesson`` ORM instance with resources loaded.

    Raises:
        LessonNotFound: If no lesson with that ID exists.
    """
    lesson = await db.scalar(
        select(Lesson)
        .where(Lesson.id == lesson_id)
        .options(selectinload(Lesson.resources))
    )
    if not lesson:
        raise LessonNotFound()
    return lesson


async def create_lesson(
    db: AsyncSession, chapter_id: uuid.UUID, body: LessonCreateIn
) -> Lesson:
    """Append a new lesson to a chapter, auto-assigning the next sequential position.

    Args:
        db: Async database session.
        chapter_id: UUID of the parent chapter.
        body: Lesson creation payload.

    Returns:
        The newly created ``Lesson`` ORM instance with resources loaded.

    Raises:
        ChapterNotFound: If the chapter does not exist.
    """
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise ChapterNotFound()
    max_pos = await db.scalar(
        select(func.max(Lesson.position)).where(Lesson.chapter_id == chapter_id)
    )
    lesson = Lesson(
        chapter_id=chapter_id,
        title=body.title,
        type=body.type,
        content=body.content,
        video_asset_id=body.video_asset_id,
        is_free_preview=body.is_free_preview,
        is_locked=body.is_locked,
        position=(max_pos or 0) + 1,
    )
    db.add(lesson)
    await db.commit()
    return await _get_lesson(db, lesson.id)


async def update_lesson(
    db: AsyncSession, lesson_id: uuid.UUID, body: LessonUpdateIn
) -> Lesson:
    """Partially update a lesson's content or metadata.

    Args:
        db: Async database session.
        lesson_id: UUID of the lesson to update.
        body: Partial update payload; ``None`` fields are left unchanged.

    Returns:
        The refreshed ``Lesson`` ORM instance with resources loaded.

    Raises:
        LessonNotFound: If the lesson does not exist.
    """
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise LessonNotFound()
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lesson, field, value)
    await db.commit()
    return await _get_lesson(db, lesson_id)


async def delete_lesson(db: AsyncSession, lesson_id: uuid.UUID) -> None:
    """Delete a lesson and cascade-delete its attached resources.

    Args:
        db: Async database session.
        lesson_id: UUID of the lesson to delete.

    Raises:
        LessonNotFound: If the lesson does not exist.
    """
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise LessonNotFound()
    await db.delete(lesson)
    await db.commit()


async def reorder_lessons(
    db: AsyncSession, chapter_id: uuid.UUID, lesson_ids: list[uuid.UUID]
) -> list[Lesson]:
    """Reorder a chapter's lessons by assigning positions from the supplied ID list.

    The caller must provide *all* lesson IDs belonging to the chapter — omitting
    or adding extra IDs raises ``InvalidLessonIds``.

    Args:
        db: Async database session.
        chapter_id: UUID of the parent chapter.
        lesson_ids: Complete ordered list of lesson UUIDs.

    Returns:
        All lessons for the chapter ordered by their new positions, with resources loaded.

    Raises:
        InvalidLessonIds: If the supplied IDs do not exactly match the chapter's lessons.
    """
    result = await db.execute(select(Lesson).where(Lesson.chapter_id == chapter_id))
    existing = list(result.scalars().all())
    if set(lesson_ids) != {lesson.id for lesson in existing}:
        raise InvalidLessonIds()
    for i, lid in enumerate(lesson_ids, start=1):
        await db.execute(
            update(Lesson)
            .where(Lesson.id == lid, Lesson.chapter_id == chapter_id)
            .values(position=i)
        )
    await db.commit()
    result = await db.execute(
        select(Lesson)
        .where(Lesson.chapter_id == chapter_id)
        .order_by(Lesson.position)
        .options(selectinload(Lesson.resources))
    )
    return list(result.scalars().all())


# ── Resources ──────────────────────────────────────────────────────────────────

async def attach_resource(
    db: AsyncSession, lesson_id: uuid.UUID, body: ResourceCreateIn
) -> LessonResource:
    """Attach a downloadable resource file to a lesson.

    Args:
        db: Async database session.
        lesson_id: UUID of the lesson to attach the resource to.
        body: Resource creation payload including URL and optional metadata.

    Returns:
        The newly created ``LessonResource`` ORM instance.

    Raises:
        LessonNotFound: If the lesson does not exist.
    """
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise LessonNotFound()
    resource = LessonResource(
        lesson_id=lesson_id,
        name=body.name,
        file_url=body.file_url,
        file_type=body.file_type,
        size_bytes=body.size_bytes,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return resource


# ── Search ─────────────────────────────────────────────────────────────────────

async def search_courses(
    db: AsyncSession, q: str, skip: int, limit: int
) -> tuple[list[Course], int]:
    """Full-text search over published, non-archived courses using PostgreSQL ``tsvector``.

    Results are ranked by ``ts_rank`` so the most relevant courses appear first.

    Args:
        db: Async database session.
        q: Search query string; converted to a ``plainto_tsquery`` expression.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(courses, total)`` where ``total`` is the unfiltered count of
        matching courses.
    """
    tsquery = func.plainto_tsquery("english", q)
    base = (
        select(Course)
        .where(
            Course.status == "published",
            Course.archived_at.is_(None),
            text("search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .options(selectinload(Course.category))
    )
    count = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.execute(
        base.order_by(func.ts_rank(Course.search_vector, tsquery).desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), count or 0
