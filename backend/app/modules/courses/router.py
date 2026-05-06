"""FastAPI router for course catalog, learner progress, and admin content management."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service as admin_service
from app.modules.admin.schemas import (
    ContentImageUploadIn,
    ContentImageUploadOut,
    CourseAnalyticsOut,
    StudentProgressRow,
)
from app.modules.courses import service
from app.modules.courses.schemas import (
    CategoryOut,
    ChapterCreateIn,
    ChapterOut,
    ChapterUpdateIn,
    CourseCreateIn,
    CourseDetail,
    CourseListItem,
    CourseUpdateIn,
    LessonCreateIn,
    LessonOut,
    LessonUpdateIn,
    ReorderIn,
    ResourceCreateIn,
    ResourceOut,
)

router = APIRouter(tags=["courses"])
admin_router = APIRouter(prefix="/admin", tags=["courses"], dependencies=[require_role(Role.ADMIN)])


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> dict:
    """List all course categories ordered alphabetically."""
    cats = await service.list_categories(db)
    return ok([CategoryOut.model_validate(c).model_dump() for c in cats])


@router.get("/courses")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    category_id: uuid.UUID | None = None,
    level: str | None = None,
    max_price: int | None = Query(None, ge=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List published courses with optional category, level, and price filters."""
    courses, total = await service.list_courses(db, category_id, level, max_price, skip, limit)
    return ok(
        [CourseListItem.model_validate(c).model_dump() for c in courses],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/courses/{slug}")
async def get_course(slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Fetch the full course detail tree by slug."""
    course = await service.get_course_by_slug(db, slug)
    return ok(CourseDetail.model_validate(course).model_dump())


@router.get("/search")
async def search(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Full-text search over published courses, ranked by relevance."""
    courses, total = await service.search_courses(db, q, skip, limit)
    return ok(
        [CourseListItem.model_validate(c).model_dump() for c in courses],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@admin_router.get("/courses")
async def list_courses_admin(
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="Filter by status: draft | published | archived"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all courses regardless of status for admin management."""
    courses, total = await service.list_all_courses(db, status, skip, limit)
    return ok(
        [CourseListItem.model_validate(c).model_dump() for c in courses],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@admin_router.get("/courses/{course_id}")
async def get_course_admin(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch any course by UUID regardless of status."""
    course = await service.get_course_by_id(db, course_id)
    return ok(CourseDetail.model_validate(course).model_dump())


@admin_router.post("/courses", status_code=201)
async def create_course(
    body: CourseCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Create a new course in draft status."""
    course = await service.create_course(db, body, created_by=current_user.id)
    return ok(CourseDetail.model_validate(course).model_dump())


@admin_router.patch("/courses/{course_id}")
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update course metadata or status."""
    course = await service.update_course(db, course_id, body)
    return ok(CourseDetail.model_validate(course).model_dump())


@admin_router.delete("/courses/{course_id}", status_code=204)
async def archive_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Archive a course, removing it from public listings."""
    await service.archive_course(db, course_id)


@admin_router.post("/courses/{course_id}/chapters", status_code=201)
async def create_chapter(
    course_id: uuid.UUID,
    body: ChapterCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Append a new chapter to a course."""
    chapter = await service.create_chapter(db, course_id, body)
    return ok(ChapterOut.model_validate(chapter).model_dump())


@admin_router.patch("/chapters/{chapter_id}")
async def update_chapter(
    chapter_id: uuid.UUID,
    body: ChapterUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a chapter's title."""
    chapter = await service.update_chapter(db, chapter_id, body)
    return ok(ChapterOut.model_validate(chapter).model_dump())


@admin_router.delete("/chapters/{chapter_id}", status_code=204)
async def delete_chapter(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a chapter and all its lessons."""
    await service.delete_chapter(db, chapter_id)


@admin_router.patch("/courses/{course_id}/chapters/reorder")
async def reorder_chapters(
    course_id: uuid.UUID,
    body: ReorderIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reorder a course's chapters by supplying the complete ordered list."""
    chapters = await service.reorder_chapters(db, course_id, body.ids)
    return ok([ChapterOut.model_validate(c).model_dump() for c in chapters])


@admin_router.post("/chapters/{chapter_id}/lessons", status_code=201)
async def create_lesson(
    chapter_id: uuid.UUID,
    body: LessonCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Append a new lesson to a chapter."""
    lesson = await service.create_lesson(db, chapter_id, body)
    if lesson.type == "text" and lesson.content:
        from app.modules.rag.tasks import index_lesson

        index_lesson.delay(str(lesson.id))
    return ok(LessonOut.model_validate(lesson).model_dump())


@admin_router.patch("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: uuid.UUID,
    body: LessonUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Partially update a lesson's content or metadata."""
    lesson = await service.update_lesson(db, lesson_id, body)
    if lesson.type == "text" and body.content is not None:
        from app.modules.rag.tasks import index_lesson

        index_lesson.delay(str(lesson.id))
    return ok(LessonOut.model_validate(lesson).model_dump())


@admin_router.get("/lessons/{lesson_id}")
async def get_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a single lesson by ID for admin editing."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.exceptions import LessonNotFound
    from app.db.models.course import Lesson

    result = await db.execute(
        select(Lesson).where(Lesson.id == lesson_id).options(selectinload(Lesson.resources))
    )
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise LessonNotFound()
    return ok(LessonOut.model_validate(lesson).model_dump())


@admin_router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a lesson and its attached resources."""
    await service.delete_lesson(db, lesson_id)


@admin_router.patch("/chapters/{chapter_id}/lessons/reorder")
async def reorder_lessons(
    chapter_id: uuid.UUID,
    body: ReorderIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reorder a chapter's lessons by supplying the complete ordered list."""
    lessons = await service.reorder_lessons(db, chapter_id, body.ids)
    return ok([LessonOut.model_validate(lesson).model_dump() for lesson in lessons])


@admin_router.post("/lessons/{lesson_id}/images/upload-url", status_code=201)
async def request_content_image_upload(
    lesson_id: uuid.UUID,
    body: ContentImageUploadIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a presigned PUT URL and permanent public URL for a lesson content image."""
    import os
    from sqlalchemy import select

    from app.core.exceptions import LessonNotFound
    from app.core.storage import generate_presigned_put, get_public_url
    from app.db.models.course import Lesson

    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise LessonNotFound()

    ext = os.path.splitext(body.filename)[-1].lstrip(".")
    key = (
        f"lessons/{lesson_id}/images/{uuid.uuid4()}.{ext}"
        if ext
        else f"lessons/{lesson_id}/images/{uuid.uuid4()}"
    )
    upload_url = generate_presigned_put(key, body.content_type)
    public_url = get_public_url(key)
    return ok(ContentImageUploadOut(upload_url=upload_url, public_url=public_url).model_dump())


@admin_router.post("/lessons/{lesson_id}/resources", status_code=201)
async def attach_resource(
    lesson_id: uuid.UUID,
    body: ResourceCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attach a downloadable resource file to a lesson."""
    resource = await service.attach_resource(db, lesson_id, body)
    return ok(ResourceOut.model_validate(resource).model_dump())


@admin_router.delete("/resources/{resource_id}", status_code=204)
async def delete_resource(
    resource_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a single lesson resource by ID."""
    await service.delete_resource(db, resource_id)


@admin_router.post("/lessons/{lesson_id}/video", status_code=201)
async def request_video_upload(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a Mux direct upload for a video lesson."""
    from sqlalchemy import select

    from app.core.exceptions import LessonNotFound
    from app.core.mux import create_upload
    from app.db.models.course import Lesson
    from app.modules.video.schemas import VideoUploadResponseOut

    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise LessonNotFound()

    upload_url, asset_id = await create_upload(cors_origin=settings.FRONTEND_URL)
    lesson.video_asset_id = asset_id
    await db.commit()
    return ok(VideoUploadResponseOut(upload_url=upload_url, asset_id=asset_id).model_dump())


@admin_router.get("/courses/{course_id}/analytics")
async def get_course_analytics(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated analytics for a course."""
    result = await admin_service.get_course_analytics(db, course_id)
    return ok(CourseAnalyticsOut.model_validate(result).model_dump())


@admin_router.get("/courses/{course_id}/students")
async def get_course_students(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Paginated progress table of all students enrolled in a course."""
    rows, total = await admin_service.get_course_students(db, course_id, skip, limit)
    return ok(
        [StudentProgressRow.model_validate(r).model_dump() for r in rows],
        meta={"total": total, "skip": skip, "limit": limit},
    )


router.include_router(admin_router)
