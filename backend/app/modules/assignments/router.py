"""API router for assignment creation, retrieval, and file submissions."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.session import get_db
from app.modules.assignments import service
from app.modules.assignments.schemas import AssignmentIn, UploadRequestIn

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post("/", status_code=201)
async def create_assignment(
    data: AssignmentIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(Role.ADMIN)),
) -> dict:
    """Create an assignment on a lesson (admin only).

    Args:
        data: Assignment creation payload.
        db: Injected async database session.
        current_user: Authenticated admin user from the JWT.

    Returns:
        The created ``AssignmentOut`` wrapped in the standard response envelope.
    """
    assignment = await service.create_assignment(db, data)
    return ok(assignment.model_dump())


@router.get("/{assignment_id}")
async def get_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(Role.STUDENT)),
) -> dict:
    """Retrieve assignment details.

    Args:
        assignment_id: UUID of the assignment to retrieve.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        The ``AssignmentOut`` wrapped in the standard response envelope.
    """
    assignment = await service.get_assignment(db, assignment_id)
    return ok(assignment.model_dump())


@router.post("/{assignment_id}/upload", status_code=201)
async def request_upload(
    assignment_id: uuid.UUID,
    data: UploadRequestIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(Role.STUDENT)),
) -> dict:
    """Request a presigned PUT URL for uploading a file to Cloudflare R2.

    Creates an ``AssignmentSubmission`` row with ``submitted_at=None`` and
    returns a URL the client should PUT the file bytes to directly.  Call
    ``POST /assignments/submissions/{id}/confirm`` after the upload completes.

    Args:
        assignment_id: UUID of the assignment to respond to.
        data: File metadata including name, MIME type, and size.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        An ``UploadResponseOut`` with the submission ID and presigned URL.
    """
    response = await service.request_upload(
        db,
        current_user.id,
        assignment_id,
        data.file_name,
        data.mime_type,
        data.file_size,
    )
    return ok(response.model_dump())


@router.post("/submissions/{submission_id}/confirm")
async def confirm_upload(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(Role.STUDENT)),
) -> dict:
    """Confirm that the direct R2 upload is complete.

    Stamps ``submitted_at`` on the submission row.  Must be called after the
    client successfully PUTs the file to the presigned URL.

    Args:
        submission_id: UUID of the ``AssignmentSubmission`` to confirm.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        The updated ``SubmissionOut`` with ``submitted_at`` populated.
    """
    submission = await service.confirm_upload(db, current_user.id, submission_id)
    return ok(submission.model_dump())


@router.get("/{assignment_id}/submissions")
async def list_submissions(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(Role.STUDENT)),
) -> dict:
    """List all submissions by the current student for an assignment.

    Args:
        assignment_id: UUID of the assignment.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        A list of ``SubmissionOut`` wrapped in the standard response envelope.
    """
    submissions = await service.list_submissions(db, current_user.id, assignment_id)
    return ok([s.model_dump() for s in submissions])
