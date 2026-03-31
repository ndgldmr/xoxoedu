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
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def create_category(db: AsyncSession, name: str) -> Category:
    slug = slugify(name)
    category = Category(name=name, slug=slug)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


# ── Courses ────────────────────────────────────────────────────────────────────

async def _generate_unique_slug(db: AsyncSession, base: str) -> str:
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
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise ChapterNotFound()
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(chapter, field, value)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def delete_chapter(db: AsyncSession, chapter_id: uuid.UUID) -> None:
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise ChapterNotFound()
    await db.delete(chapter)
    await db.commit()


async def reorder_chapters(
    db: AsyncSession, course_id: uuid.UUID, chapter_ids: list[uuid.UUID]
) -> list[Chapter]:
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
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise LessonNotFound()
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lesson, field, value)
    await db.commit()
    return await _get_lesson(db, lesson_id)


async def delete_lesson(db: AsyncSession, lesson_id: uuid.UUID) -> None:
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise LessonNotFound()
    await db.delete(lesson)
    await db.commit()


async def reorder_lessons(
    db: AsyncSession, chapter_id: uuid.UUID, lesson_ids: list[uuid.UUID]
) -> list[Lesson]:
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
