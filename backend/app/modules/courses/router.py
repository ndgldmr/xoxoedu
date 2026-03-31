import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.db.session import get_db
from app.modules.courses import service
from app.modules.courses.schemas import (
    CategoryOut,
    CourseDetail,
    CourseListItem,
)

router = APIRouter(tags=["courses"])


# ── Categories ─────────────────────────────────────────────────────────────────

@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> dict:
    cats = await service.list_categories(db)
    return ok([CategoryOut.model_validate(c).model_dump() for c in cats])


# ── Courses ────────────────────────────────────────────────────────────────────

@router.get("/courses")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    category_id: uuid.UUID | None = None,
    level: str | None = None,
    max_price: int | None = Query(None, ge=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    courses, total = await service.list_courses(db, category_id, level, max_price, skip, limit)
    return ok(
        [CourseListItem.model_validate(c).model_dump() for c in courses],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/courses/{slug}")
async def get_course(slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    course = await service.get_course_by_slug(db, slug)
    return ok(CourseDetail.model_validate(course).model_dump())


# ── Search ─────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    courses, total = await service.search_courses(db, q, skip, limit)
    return ok(
        [CourseListItem.model_validate(c).model_dump() for c in courses],
        meta={"total": total, "skip": skip, "limit": limit},
    )
