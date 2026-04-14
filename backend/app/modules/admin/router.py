"""FastAPI router for admin-only user and course-management endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminSubmissionOut,
    AnnouncementIn,
    AnnouncementOut,
    CourseAnalyticsOut,
    CouponCreateIn,
    CouponOut,
    CouponUpdateIn,
    GradeSubmissionIn,
    PlatformAnalyticsOut,
    RefundOut,
    RoleUpdateIn,
    StudentProgressRow,
)
from app.modules.assignments import service as assignment_service
from app.modules.assignments.schemas import AssignmentIn
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
from app.modules.quizzes import service as quiz_service
from app.modules.quizzes.schemas import QuizIn

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[require_role(Role.ADMIN)])


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all users with pagination metadata."""
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
    """Change the role of a user."""
    user = await service.update_role(db, user_id, body.role.value)
    return ok(UserOut.model_validate(user).model_dump())


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a user account."""
    await service.delete_user(db, user_id)


# ── Courses ────────────────────────────────────────────────────────────────────

@router.post("/courses", status_code=201)
async def create_course(
    body: CourseCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Create a new course in draft status."""
    course = await course_service.create_course(db, body, created_by=current_user.id)
    return ok(CourseDetail.model_validate(course).model_dump())


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update course metadata or status, subject to valid status transitions."""
    course = await course_service.update_course(db, course_id, body)
    return ok(CourseDetail.model_validate(course).model_dump())


@router.delete("/courses/{course_id}", status_code=204)
async def archive_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Archive a course, removing it from public listings."""
    await course_service.archive_course(db, course_id)


# ── Chapters ───────────────────────────────────────────────────────────────────

@router.post("/courses/{course_id}/chapters", status_code=201)
async def create_chapter(
    course_id: uuid.UUID,
    body: ChapterCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Append a new chapter to a course, auto-assigning the next position."""
    chapter = await course_service.create_chapter(db, course_id, body)
    return ok(ChapterOut.model_validate(chapter).model_dump())


@router.patch("/chapters/{chapter_id}")
async def update_chapter(
    chapter_id: uuid.UUID,
    body: ChapterUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a chapter's title."""
    chapter = await course_service.update_chapter(db, chapter_id, body)
    return ok(ChapterOut.model_validate(chapter).model_dump())


@router.delete("/chapters/{chapter_id}", status_code=204)
async def delete_chapter(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a chapter and all its lessons."""
    await course_service.delete_chapter(db, chapter_id)


@router.patch("/courses/{course_id}/chapters/reorder")
async def reorder_chapters(
    course_id: uuid.UUID,
    body: ReorderIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reorder a course's chapters by supplying the complete ordered list of chapter IDs."""
    chapters = await course_service.reorder_chapters(db, course_id, body.ids)
    return ok([ChapterOut.model_validate(c).model_dump() for c in chapters])


# ── Lessons ────────────────────────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/lessons", status_code=201)
async def create_lesson(
    chapter_id: uuid.UUID,
    body: LessonCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Append a new lesson to a chapter, auto-assigning the next position."""
    lesson = await course_service.create_lesson(db, chapter_id, body)
    return ok(LessonOut.model_validate(lesson).model_dump())


@router.patch("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: uuid.UUID,
    body: LessonUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Partially update a lesson's content or metadata."""
    lesson = await course_service.update_lesson(db, lesson_id, body)
    return ok(LessonOut.model_validate(lesson).model_dump())


@router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a lesson and its attached resources."""
    await course_service.delete_lesson(db, lesson_id)


@router.patch("/chapters/{chapter_id}/lessons/reorder")
async def reorder_lessons(
    chapter_id: uuid.UUID,
    body: ReorderIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reorder a chapter's lessons by supplying the complete ordered list of lesson IDs."""
    lessons = await course_service.reorder_lessons(db, chapter_id, body.ids)
    return ok([LessonOut.model_validate(lesson).model_dump() for lesson in lessons])


# ── Video upload ───────────────────────────────────────────────────────────────

@router.post("/lessons/{lesson_id}/video", status_code=201)
async def request_video_upload(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a Mux direct upload for a video lesson.

    Returns a presigned upload URL the client should PUT the video file to
    directly.  The Mux upload ID is persisted on the lesson row so the webhook
    handler can correlate the ``video.upload.asset_created`` event back to this
    lesson and swap in the real asset ID.

    Args:
        lesson_id: UUID of the lesson to attach the video to.
        db: Async database session.

    Returns:
        ``VideoUploadResponseOut`` with ``upload_url`` and ``asset_id``.

    Raises:
        LessonNotFound: When no lesson with ``lesson_id`` exists.
    """
    from sqlalchemy import select

    from app.core.exceptions import LessonNotFound
    from app.core.mux import create_upload
    from app.db.models.course import Lesson
    from app.modules.video.schemas import VideoUploadResponseOut

    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise LessonNotFound()

    upload_url, asset_id = create_upload(
        cors_origin=settings.FRONTEND_URL,
    )
    lesson.video_asset_id = asset_id
    await db.commit()

    return ok(VideoUploadResponseOut(upload_url=upload_url, asset_id=asset_id).model_dump())


# ── Resources ──────────────────────────────────────────────────────────────────

@router.post("/lessons/{lesson_id}/resources", status_code=201)
async def attach_resource(
    lesson_id: uuid.UUID,
    body: ResourceCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attach a downloadable resource file to a lesson."""
    resource = await course_service.attach_resource(db, lesson_id, body)
    return ok(ResourceOut.model_validate(resource).model_dump())


# ── Quizzes ─────────────────────────────────────────────────────────────────────

@router.post("/quizzes", status_code=201)
async def create_quiz(
    data: QuizIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a quiz with questions on a lesson."""
    quiz = await quiz_service.create_quiz(db, data)
    return ok(quiz.model_dump())


# ── Assignments ─────────────────────────────────────────────────────────────────

@router.post("/assignments", status_code=201)
async def create_assignment(
    data: AssignmentIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an assignment on a lesson."""
    assignment = await assignment_service.create_assignment(db, data)
    return ok(assignment.model_dump())


# ── Coupons ─────────────────────────────────────────────────────────────────────

@router.post("/coupons", status_code=201)
async def create_coupon(
    data: CouponCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a discount coupon."""
    coupon = await service.create_coupon(db, data)
    return ok(CouponOut.model_validate(coupon).model_dump())


@router.get("/coupons")
async def list_coupons(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all coupons with usage stats."""
    coupons, total = await service.list_coupons(db, skip, limit)
    return ok(
        [CouponOut.model_validate(c).model_dump() for c in coupons],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.patch("/coupons/{coupon_id}")
async def update_coupon(
    coupon_id: uuid.UUID,
    data: CouponUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a coupon's expiry date and/or usage cap."""
    coupon = await service.update_coupon(db, coupon_id, data)
    return ok(CouponOut.model_validate(coupon).model_dump())


@router.delete("/coupons/{coupon_id}", status_code=204)
async def delete_coupon(
    coupon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a coupon."""
    await service.delete_coupon(db, coupon_id)


# ── Payments ─────────────────────────────────────────────────────────────────────

@router.get("/payments")
async def list_payments(
    db: AsyncSession = Depends(get_db),
    course_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all payments across the platform, with optional course and status filters."""
    payments, total = await service.list_payments_admin(db, course_id, status, skip, limit)
    return ok(
        [p.model_dump() for p in payments],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.post("/payments/{payment_id}/refund")
async def refund_payment(
    payment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a Stripe refund for a completed payment."""
    result = await service.refund_payment(db, payment_id)
    return ok(RefundOut.model_validate(result).model_dump())


# ── Grading ─────────────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/submissions")
async def list_submissions(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="ungraded | graded | flagged"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List the assignment submission queue for a course, oldest-first."""
    submissions, total = await service.list_submissions(db, course_id, status, skip, limit)
    return ok(
        [AdminSubmissionOut.model_validate(s).model_dump() for s in submissions],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.patch("/submissions/{submission_id}/grade")
async def grade_submission(
    submission_id: uuid.UUID,
    data: GradeSubmissionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Save a grade (draft or published) on an assignment submission."""
    result = await service.grade_submission(db, submission_id, current_user.id, data)
    return ok(AdminSubmissionOut.model_validate(result).model_dump())


@router.post("/submissions/{submission_id}/reopen")
async def reopen_submission(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Allow a student to upload a new attempt for this submission."""
    result = await service.reopen_submission(db, submission_id)
    return ok(AdminSubmissionOut.model_validate(result).model_dump())


# ── Analytics ─────────────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/analytics")
async def get_course_analytics(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated analytics for a course: enrollments, quiz scores, lesson drop-off."""
    result = await service.get_course_analytics(db, course_id)
    return ok(CourseAnalyticsOut.model_validate(result).model_dump())


@router.get("/courses/{course_id}/students")
async def get_course_students(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Paginated progress table of all students enrolled in a course."""
    rows, total = await service.get_course_students(db, course_id, skip, limit)
    return ok(
        [StudentProgressRow.model_validate(r).model_dump() for r in rows],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/analytics/platform")
async def get_platform_analytics(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Platform-wide aggregated metrics: students, enrollments, revenue, top courses."""
    result = await service.get_platform_analytics(db)
    return ok(PlatformAnalyticsOut.model_validate(result).model_dump())


# ── Announcements ─────────────────────────────────────────────────────────────────

@router.post("/announcements", status_code=201)
async def create_announcement(
    data: AnnouncementIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Create an announcement and dispatch emails to targeted students."""
    result = await service.create_announcement(db, current_user.id, data)
    return ok(AnnouncementOut.model_validate(result).model_dump())


@router.get("/announcements")
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all announcements, newest first."""
    announcements, total = await service.list_announcements(db, skip, limit)
    return ok(
        [AnnouncementOut.model_validate(a).model_dump() for a in announcements],
        meta={"total": total, "skip": skip, "limit": limit},
    )
