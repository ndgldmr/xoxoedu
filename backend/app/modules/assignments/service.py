"""Business logic for assignment creation and file-upload submission flow."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AssignmentNotFound,
    AssignmentSubmissionNotFound,
    UploadFailed,
)
from app.core.storage import generate_presigned_put
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.modules.assignments.schemas import (
    AssignmentIn,
    AssignmentOut,
    SubmissionOut,
    UploadResponseOut,
)

_PRESIGNED_TTL_SECONDS = 300  # 5 minutes


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> Assignment:
    """Load an ``Assignment`` row or raise ``AssignmentNotFound``.

    Args:
        db: Active async database session.
        assignment_id: UUID of the assignment to load.

    Returns:
        The ``Assignment`` ORM instance.

    Raises:
        AssignmentNotFound: When no assignment with ``assignment_id`` exists.
    """
    result = await db.execute(
        select(Assignment).where(Assignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise AssignmentNotFound()
    return assignment


# ── Public service functions ───────────────────────────────────────────────────

async def create_assignment(db: AsyncSession, data: AssignmentIn) -> AssignmentOut:
    """Create a new assignment on a lesson.

    Args:
        db: Active async database session.
        data: Validated ``AssignmentIn`` payload.

    Returns:
        An ``AssignmentOut`` representing the newly created assignment.
    """
    assignment = Assignment(
        lesson_id=data.lesson_id,
        title=data.title,
        instructions=data.instructions,
        max_file_size_bytes=data.max_file_size_bytes,
        allowed_extensions=data.allowed_extensions,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return AssignmentOut.model_validate(assignment)


async def get_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> AssignmentOut:
    """Return an assignment by ID.

    Args:
        db: Active async database session.
        assignment_id: UUID of the assignment to retrieve.

    Returns:
        An ``AssignmentOut`` for the requested assignment.

    Raises:
        AssignmentNotFound: When no assignment with ``assignment_id`` exists.
    """
    assignment = await _get_assignment(db, assignment_id)
    return AssignmentOut.model_validate(assignment)


async def request_upload(
    db: AsyncSession,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    file_name: str,
    mime_type: str,
    file_size: int,
) -> UploadResponseOut:
    """Create an ``AssignmentSubmission`` row and return a presigned PUT URL.

    The student should PUT the file bytes directly to the returned URL.  The
    submission row is created with ``submitted_at=None``; the student must call
    ``confirm_upload`` once the upload is complete.

    Args:
        db: Active async database session.
        user_id: UUID of the uploading student.
        assignment_id: UUID of the assignment being responded to.
        file_name: Original filename; used as the final segment of the R2 key.
        mime_type: MIME type of the file being uploaded.
        file_size: File size in bytes declared by the student.

    Returns:
        An ``UploadResponseOut`` containing the submission ID and presigned URL.

    Raises:
        AssignmentNotFound: When no assignment with ``assignment_id`` exists.
        UploadFailed: When the presigned URL cannot be generated.
    """
    assignment = await _get_assignment(db, assignment_id)

    # Validate extension if the assignment restricts it
    if assignment.allowed_extensions:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext not in [e.lower() for e in assignment.allowed_extensions]:
            from app.core.exceptions import AppException

            raise AppException(
                f"File type '.{ext}' is not allowed. "
                f"Allowed: {', '.join(assignment.allowed_extensions)}"
            )

    # Validate file size
    if file_size > assignment.max_file_size_bytes:
        from app.core.exceptions import AppException

        raise AppException(
            f"File size {file_size} bytes exceeds the limit of "
            f"{assignment.max_file_size_bytes} bytes."
        )

    key = f"assignments/{assignment_id}/{uuid.uuid4()}/{file_name}"
    expires_at = datetime.now(UTC) + timedelta(seconds=_PRESIGNED_TTL_SECONDS)

    try:
        upload_url = generate_presigned_put(key, mime_type, _PRESIGNED_TTL_SECONDS)
    except Exception as exc:
        raise UploadFailed() from exc

    submission = AssignmentSubmission(
        user_id=user_id,
        assignment_id=assignment_id,
        file_key=key,
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type,
        scan_status="pending",
        upload_url_expires_at=expires_at,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    return UploadResponseOut(
        submission_id=submission.id,
        upload_url=upload_url,
        expires_at=expires_at,
    )


async def confirm_upload(
    db: AsyncSession, user_id: uuid.UUID, submission_id: uuid.UUID
) -> SubmissionOut:
    """Stamp ``submitted_at`` once the student's direct upload to R2 is complete.

    Args:
        db: Active async database session.
        user_id: UUID of the confirming student; used to scope access.
        submission_id: UUID of the ``AssignmentSubmission`` to confirm.

    Returns:
        The updated ``SubmissionOut`` with ``submitted_at`` set.

    Raises:
        AssignmentSubmissionNotFound: When no matching submission exists for this student.
    """
    result = await db.execute(
        select(AssignmentSubmission).where(
            AssignmentSubmission.id == submission_id,
            AssignmentSubmission.user_id == user_id,
        )
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise AssignmentSubmissionNotFound()

    submission.submitted_at = datetime.now(UTC)
    submission.upload_url_expires_at = None
    await db.commit()
    await db.refresh(submission)
    return SubmissionOut.model_validate(submission)


async def list_submissions(
    db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> list[SubmissionOut]:
    """Return all submissions by a student for a given assignment.

    Args:
        db: Active async database session.
        user_id: UUID of the student.
        assignment_id: UUID of the assignment.

    Returns:
        A list of ``SubmissionOut`` ordered by creation time.

    Raises:
        AssignmentNotFound: When no assignment with ``assignment_id`` exists.
    """
    await _get_assignment(db, assignment_id)

    result = await db.execute(
        select(AssignmentSubmission)
        .where(
            AssignmentSubmission.user_id == user_id,
            AssignmentSubmission.assignment_id == assignment_id,
        )
        .order_by(AssignmentSubmission.created_at)
    )
    return [SubmissionOut.model_validate(s) for s in result.scalars().all()]


async def get_submission(
    db: AsyncSession, user_id: uuid.UUID, submission_id: uuid.UUID
) -> SubmissionOut:
    """Return a single assignment submission belonging to the requesting student.

    Args:
        db: Active async database session.
        user_id: UUID of the requesting student; used to scope access.
        submission_id: UUID of the submission to retrieve.

    Returns:
        The ``SubmissionOut`` for the requested submission.

    Raises:
        AssignmentSubmissionNotFound: When no matching submission exists for this student.
    """
    result = await db.execute(
        select(AssignmentSubmission).where(
            AssignmentSubmission.id == submission_id,
            AssignmentSubmission.user_id == user_id,
        )
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise AssignmentSubmissionNotFound()
    return SubmissionOut.model_validate(submission)
