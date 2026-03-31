import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service
from app.modules.admin.schemas import RoleUpdateIn
from app.modules.auth.schemas import UserOut
from app.modules.courses import service as course_service
from app.modules.courses.schemas import (
    ChapterCreateIn,
    ChapterOut,
    ChapterUpdateIn,
    CourseCreateIn,
    CourseDetail,
    CourseUpdateIn,
    LessonCreateIn,
    LessonOut,
    LessonUpdateIn,
    ReorderIn,
    ResourceCreateIn,
    ResourceOut,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[require_role(Role.ADMIN)])


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    users, total = await service.list_users(db, skip, limit)
    return ok(
        [UserOut.model_validate(u).model_dump() for u in users],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    body: RoleUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await service.update_role(db, user_id, body.role.value)
    return ok(UserOut.model_validate(user).model_dump())


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_user(db, user_id)


# ── Courses ────────────────────────────────────────────────────────────────────

@router.post("/courses", status_code=201)
async def create_course(
    body: CourseCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    course = await course_service.create_course(db, body, created_by=current_user.id)
    return ok(CourseDetail.model_validate(course).model_dump())


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    course = await course_service.update_course(db, course_id, body)
    return ok(CourseDetail.model_validate(course).model_dump())


@router.delete("/courses/{course_id}", status_code=204)
async def archive_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await course_service.archive_course(db, course_id)


# ── Chapters ───────────────────────────────────────────────────────────────────

@router.post("/courses/{course_id}/chapters", status_code=201)
async def create_chapter(
    course_id: uuid.UUID,
    body: ChapterCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    chapter = await course_service.create_chapter(db, course_id, body)
    return ok(ChapterOut.model_validate(chapter).model_dump())


@router.patch("/chapters/{chapter_id}")
async def update_chapter(
    chapter_id: uuid.UUID,
    body: ChapterUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    chapter = await course_service.update_chapter(db, chapter_id, body)
    return ok(ChapterOut.model_validate(chapter).model_dump())


@router.delete("/chapters/{chapter_id}", status_code=204)
async def delete_chapter(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await course_service.delete_chapter(db, chapter_id)


@router.patch("/courses/{course_id}/chapters/reorder")
async def reorder_chapters(
    course_id: uuid.UUID,
    body: ReorderIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    chapters = await course_service.reorder_chapters(db, course_id, body.ids)
    return ok([ChapterOut.model_validate(c).model_dump() for c in chapters])


# ── Lessons ────────────────────────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/lessons", status_code=201)
async def create_lesson(
    chapter_id: uuid.UUID,
    body: LessonCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    lesson = await course_service.create_lesson(db, chapter_id, body)
    return ok(LessonOut.model_validate(lesson).model_dump())


@router.patch("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: uuid.UUID,
    body: LessonUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    lesson = await course_service.update_lesson(db, lesson_id, body)
    return ok(LessonOut.model_validate(lesson).model_dump())


@router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await course_service.delete_lesson(db, lesson_id)


@router.patch("/chapters/{chapter_id}/lessons/reorder")
async def reorder_lessons(
    chapter_id: uuid.UUID,
    body: ReorderIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    lessons = await course_service.reorder_lessons(db, chapter_id, body.ids)
    return ok([LessonOut.model_validate(lesson).model_dump() for lesson in lessons])


# ── Resources ──────────────────────────────────────────────────────────────────

@router.post("/lessons/{lesson_id}/resources", status_code=201)
async def attach_resource(
    lesson_id: uuid.UUID,
    body: ResourceCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    resource = await course_service.attach_resource(db, lesson_id, body)
    return ok(ResourceOut.model_validate(resource).model_dump())
