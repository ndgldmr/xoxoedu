"""API router for assignments, uploads, and admin grading flows."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.admin import service as admin_service
from app.modules.admin.schemas import AdminSubmissionDetailOut, AdminSubmissionOut, GradeSubmissionIn
from app.modules.assignments import service
from app.modules.assignments.schemas import AssignmentIn, AssignmentUpdateIn, UploadRequestIn

router = APIRouter(tags=["assignments"])
admin_router = APIRouter(
    prefix="/admin",
    tags=["assignments"],
    dependencies=[require_role(Role.ADMIN)],
)


@router.get("/lessons/{lesson_id}/assignment")
async def get_assignment_by_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Retrieve the assignment for a lesson by ``lesson_id``."""
    assignment = await service.get_assignment_by_lesson(db, lesson_id)
    return ok(assignment.model_dump())


@router.get("/assignments/{assignment_id}")
async def get_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Retrieve assignment details."""
    assignment = await service.get_assignment(db, assignment_id)
    return ok(assignment.model_dump())


@router.post("/assignments/{assignment_id}/uploads", status_code=201)
async def request_upload(
    assignment_id: uuid.UUID,
    data: UploadRequestIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Request a presigned PUT URL for uploading an assignment file."""
    response = await service.request_upload(
        db,
        current_user.id,
        assignment_id,
        data.file_name,
        data.mime_type,
        data.file_size,
    )
    return ok(response.model_dump())


@router.post("/assignments/submissions/{submission_id}/confirm")
async def confirm_upload(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Confirm that the direct file upload is complete."""
    submission = await service.confirm_upload(db, current_user.id, submission_id)
    return ok(submission.model_dump())


@router.get("/assignments/{assignment_id}/submissions")
async def list_submissions(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """List all submissions by the current student for an assignment."""
    submissions = await service.list_submissions(db, current_user.id, assignment_id)
    return ok([s.model_dump() for s in submissions])


@admin_router.post("/assignments", status_code=201)
async def create_assignment(
    data: AssignmentIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an assignment on a lesson."""
    assignment = await service.create_assignment(db, data)
    return ok(assignment.model_dump())


@admin_router.get("/lessons/{lesson_id}/assignment")
async def get_assignment_admin(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch the assignment attached to a lesson."""
    assignment = await service.get_assignment_by_lesson(db, lesson_id)
    return ok(assignment.model_dump())


@admin_router.patch("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: uuid.UUID,
    data: AssignmentUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Partially update an assignment's fields."""
    assignment = await service.update_assignment(db, assignment_id, data)
    return ok(assignment.model_dump())


@admin_router.get("/submissions/{submission_id}")
async def get_submission_detail(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch a single assignment submission with a presigned download URL."""
    result = await admin_service.get_submission_detail(db, submission_id)
    return ok(AdminSubmissionDetailOut.model_validate(result).model_dump())


@admin_router.get("/courses/{course_id}/submissions")
async def list_course_submissions(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="ungraded | graded | flagged"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List the assignment submission queue for a course, oldest first."""
    submissions, total = await admin_service.list_submissions(db, course_id, status, skip, limit)
    return ok(
        [AdminSubmissionOut.model_validate(s).model_dump() for s in submissions],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@admin_router.patch("/submissions/{submission_id}/grade")
async def grade_submission(
    submission_id: uuid.UUID,
    data: GradeSubmissionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Save a grade draft or publish a grade for an assignment submission."""
    result = await admin_service.grade_submission(db, submission_id, current_user.id, data)
    return ok(AdminSubmissionOut.model_validate(result).model_dump())


@admin_router.post("/submissions/{submission_id}/reopen")
async def reopen_submission(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Allow a student to upload a new attempt for this submission."""
    result = await admin_service.reopen_submission(db, submission_id)
    return ok(AdminSubmissionOut.model_validate(result).model_dump())


router.include_router(admin_router)
