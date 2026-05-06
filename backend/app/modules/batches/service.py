"""Business logic for batch CRUD, enrollment, and transfer workflows."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.types import Float as SAFloat

from app.core.exceptions import (
    AlreadyInBatch,
    BatchArchived,
    BatchAtCapacity,
    BatchEnrollmentNotFound,
    BatchNotFound,
    BatchNotOpenForEnrollment,
    BatchProgramMismatch,
    BatchTransferCurrentBatchRequired,
    BatchTransferProgramMismatch,
    BatchTransferRequestAlreadyPending,
    BatchTransferRequestAlreadyResolved,
    BatchTransferRequestNotFound,
    BatchTransferSameBatch,
    InvalidStatusTransition,
    ProgramEnrollmentRequired,
    ProgramNotFound,
    StudentAlreadyInActiveBatch,
    StudentAlreadyInProgramBatch,
    UserNotFound,
)
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.batch import Batch, BatchEnrollment, BatchTransferRequest
from app.db.models.course import Chapter, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.quiz import Quiz, QuizSubmission
from app.db.models.user import User
from app.modules.batches.schemas import (
    BatchStudentProgressOut,
    StudentCourseProgressOut,
    VALID_TRANSFER_REQUEST_TRANSITIONS,
    VALID_TRANSITIONS,
)

# ── Pure helpers ───────────────────────────────────────────────────────────────

def validate_status_transition(current: str, new: str) -> None:
    """Raise ``InvalidStatusTransition`` if the status change is not permitted.

    Allowed transitions:
    - ``upcoming`` → ``active`` or ``archived``
    - ``active`` → ``archived``
    - ``archived`` → (nothing)

    Args:
        current: The batch's current status string.
        new: The desired new status string.

    Raises:
        InvalidStatusTransition: If ``new`` is not reachable from ``current``.
    """
    if new not in VALID_TRANSITIONS.get(current, set()):
        raise InvalidStatusTransition(
            f"Cannot transition batch from '{current}' to '{new}'"
        )


def validate_transfer_request_transition(current: str, new: str) -> None:
    """Raise when the transfer-request status change is not permitted."""
    if new not in VALID_TRANSFER_REQUEST_TRANSITIONS.get(current, set()):
        raise InvalidStatusTransition(
            f"Cannot transition batch transfer request from '{current}' to '{new}'"
        )


def _is_batch_open_for_enrollment(
    batch: Batch,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a batch is currently open for student selection."""
    now = now or datetime.now(UTC)
    if batch.status not in {"upcoming", "active"}:
        return False
    if batch.enrollment_opens_at is not None and now < batch.enrollment_opens_at:
        return False
    return batch.enrollment_closes_at is None or now <= batch.enrollment_closes_at


def _remaining_seats(batch: Batch, member_count: int) -> int:
    """Return the non-negative remaining seat count for a batch."""
    return max(batch.capacity - member_count, 0)


# ── Internal DB helpers ────────────────────────────────────────────────────────

async def _get_batch(db: AsyncSession, batch_id: uuid.UUID) -> Batch:
    """Fetch a batch by primary key or raise ``BatchNotFound``."""
    batch = await db.get(Batch, batch_id)
    if not batch:
        raise BatchNotFound()
    return batch


async def _get_batch_locked(db: AsyncSession, batch_id: uuid.UUID) -> Batch:
    """Fetch a batch with a row-level FOR UPDATE lock for concurrent capacity checks."""
    batch = await db.scalar(
        select(Batch).where(Batch.id == batch_id).with_for_update()
    )
    if not batch:
        raise BatchNotFound()
    return batch


async def _get_batch_transfer_request_locked(
    db: AsyncSession,
    request_id: uuid.UUID,
) -> BatchTransferRequest:
    """Fetch a transfer request with a row-level lock or raise."""
    request = await db.scalar(
        select(BatchTransferRequest)
        .where(BatchTransferRequest.id == request_id)
        .with_for_update()
    )
    if not request:
        raise BatchTransferRequestNotFound()
    return request


async def _get_active_program_enrollment(
    db: AsyncSession,
    user_id: uuid.UUID,
    program_id: uuid.UUID,
    *,
    lock: bool = False,
) -> ProgramEnrollment:
    """Return the user's active program enrollment for the given program.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        program_id: UUID of the program.

    Returns:
        The active ``ProgramEnrollment`` instance.

    Raises:
        UserNotFound: If no user with the given ID exists.
        ProgramEnrollmentRequired: If the student has no active enrollment in this program.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()

    stmt = select(ProgramEnrollment).where(
        ProgramEnrollment.user_id == user_id,
        ProgramEnrollment.program_id == program_id,
        ProgramEnrollment.status == "active",
    )
    if lock:
        stmt = stmt.with_for_update()

    enrollment = await db.scalar(stmt)
    if not enrollment:
        raise ProgramEnrollmentRequired()
    return enrollment


async def _get_current_active_program_enrollment(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    lock: bool = False,
) -> ProgramEnrollment:
    """Return the user's single active program enrollment or raise."""
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()

    stmt = select(ProgramEnrollment).where(
        ProgramEnrollment.user_id == user_id,
        ProgramEnrollment.status == "active",
    )
    if lock:
        stmt = stmt.with_for_update()

    enrollment = await db.scalar(stmt)
    if not enrollment:
        raise ProgramEnrollmentRequired()
    return enrollment


async def _get_current_batch_membership_for_program(
    db: AsyncSession,
    user_id: uuid.UUID,
    program_id: uuid.UUID,
    *,
    lock: bool = False,
) -> BatchEnrollment | None:
    """Return the user's current batch membership for a specific program."""
    stmt = (
        select(BatchEnrollment)
        .join(Batch, BatchEnrollment.batch_id == Batch.id)
        .where(
            BatchEnrollment.user_id == user_id,
            Batch.program_id == program_id,
        )
        .order_by(BatchEnrollment.enrolled_at.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt.options(selectinload(BatchEnrollment.batch)))


async def _get_pending_transfer_request_for_program(
    db: AsyncSession,
    user_id: uuid.UUID,
    program_id: uuid.UUID,
) -> BatchTransferRequest | None:
    """Return a pending request for the user's current program, if any."""
    rows = await db.scalars(
        select(BatchTransferRequest)
        .where(
            BatchTransferRequest.user_id == user_id,
            BatchTransferRequest.status == "pending",
        )
        .options(
            selectinload(BatchTransferRequest.from_batch),
            selectinload(BatchTransferRequest.to_batch),
        )
    )
    for request in rows.all():
        if request.from_batch and request.from_batch.program_id == program_id:
            return request
        if request.to_batch and request.to_batch.program_id == program_id:
            return request
    return None


async def _count_batch_members(db: AsyncSession, batch_id: uuid.UUID) -> int:
    """Return the current member count for a batch."""
    return int(
        await db.scalar(
            select(func.count(BatchEnrollment.id)).where(BatchEnrollment.batch_id == batch_id)
        )
        or 0
    )


async def _get_transfer_request_with_related(
    db: AsyncSession,
    request_id: uuid.UUID,
) -> BatchTransferRequest:
    """Return a transfer request with related user and batch objects loaded."""
    request = await db.scalar(
        select(BatchTransferRequest)
        .where(BatchTransferRequest.id == request_id)
        .options(
            selectinload(BatchTransferRequest.user),
            selectinload(BatchTransferRequest.from_batch),
            selectinload(BatchTransferRequest.to_batch),
            selectinload(BatchTransferRequest.reviewer),
        )
    )
    if not request:
        raise BatchTransferRequestNotFound()
    return request


# ── Batch CRUD ─────────────────────────────────────────────────────────────────

async def create_batch(
    db: AsyncSession,
    program_id: uuid.UUID,
    title: str,
    timezone: str,
    starts_at: object,
    ends_at: object,
    enrollment_opens_at: object | None,
    enrollment_closes_at: object | None,
    capacity: int | None,
) -> Batch:
    """Create a new batch for a program.

    Args:
        db: Async database session.
        program_id: UUID of the program this batch belongs to.
        title: Human-readable cohort label.
        timezone: IANA timezone name for display and scheduling.
        starts_at: UTC datetime when the cohort period begins.
        ends_at: UTC datetime when the cohort period ends.
        enrollment_opens_at: Optional UTC datetime when enrollment opens.
        enrollment_closes_at: Optional UTC datetime when enrollment closes.
        capacity: Maximum seat count; ``None`` defaults to 15.

    Returns:
        The newly created ``Batch`` ORM instance.

    Raises:
        ProgramNotFound: If the program does not exist.
    """
    program = await db.get(Program, program_id)
    if not program:
        raise ProgramNotFound()

    batch = Batch(
        program_id=program_id,
        title=title,
        timezone=timezone,
        starts_at=starts_at,
        ends_at=ends_at,
        enrollment_opens_at=enrollment_opens_at,
        enrollment_closes_at=enrollment_closes_at,
        capacity=capacity if capacity is not None else 15,
        status="upcoming",
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def get_batch(db: AsyncSession, batch_id: uuid.UUID) -> Batch:
    """Return a batch by primary key."""
    return await _get_batch(db, batch_id)


async def list_batches(
    db: AsyncSession,
    program_id: uuid.UUID,
    status: str | None,
    skip: int,
    limit: int,
) -> tuple[list[Batch], int]:
    """Return a paginated list of batches for a program.

    Args:
        db: Async database session.
        program_id: UUID of the program to filter by.
        status: Optional status filter.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(batches, total)`` where ``total`` is the unfiltered count.
    """
    base = select(Batch).where(Batch.program_id == program_id)
    if status:
        base = base.where(Batch.status == status)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(Batch.starts_at.asc()).offset(skip).limit(limit)
    )
    return list(rows.all()), total or 0


async def update_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    title: str | None,
    timezone: str | None,
    starts_at: object | None,
    ends_at: object | None,
    enrollment_opens_at: object | None,
    enrollment_closes_at: object | None,
    capacity: int | None,
    status: str | None,
) -> Batch:
    """Apply a partial update to a batch.

    Archived batches are read-only: any attempt to update them raises
    ``BatchArchived``.  Status changes are validated against the allowed
    transition graph.

    Raises:
        BatchNotFound: If the batch does not exist.
        BatchArchived: If the batch is already archived.
        InvalidStatusTransition: If the requested status change is not permitted.
    """
    batch = await _get_batch(db, batch_id)

    if batch.status == "archived":
        raise BatchArchived()

    if status is not None:
        validate_status_transition(batch.status, status)
        batch.status = status

    if title is not None:
        batch.title = title
    if timezone is not None:
        batch.timezone = timezone
    if starts_at is not None:
        batch.starts_at = starts_at
    if ends_at is not None:
        batch.ends_at = ends_at
    if enrollment_opens_at is not None:
        batch.enrollment_opens_at = enrollment_opens_at
    if enrollment_closes_at is not None:
        batch.enrollment_closes_at = enrollment_closes_at
    if capacity is not None:
        batch.capacity = capacity

    await db.commit()
    await db.refresh(batch)
    return batch


# ── Batch enrollment ───────────────────────────────────────────────────────────

async def add_member(
    db: AsyncSession,
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
) -> BatchEnrollment:
    """Add a student to a batch.

    Requires the student to have an active ``ProgramEnrollment`` for the
    batch's program.  The batch is locked with ``FOR UPDATE`` before the
    capacity check to prevent concurrent overbooking.

    Args:
        db: Async database session.
        batch_id: UUID of the target batch.
        user_id: UUID of the student to add.

    Returns:
        The new ``BatchEnrollment`` ORM instance with ``user`` loaded.

    Raises:
        BatchNotFound: If the batch does not exist.
        BatchArchived: If the batch is archived.
        BatchAtCapacity: If the batch has no remaining seats.
        AlreadyInBatch: If the student is already a member of this batch.
        StudentAlreadyInActiveBatch: If the student is already in an active batch
            for the same program.
        UserNotFound: If no user with the given ID exists.
        ProgramEnrollmentRequired: If the student has no active program enrollment.
    """
    batch = await _get_batch_locked(db, batch_id)

    if batch.status == "archived":
        raise BatchArchived()

    if await _count_batch_members(db, batch_id) >= batch.capacity:
        raise BatchAtCapacity()

    existing = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.batch_id == batch_id,
            BatchEnrollment.user_id == user_id,
        )
    )
    if existing:
        raise AlreadyInBatch()

    # Reject if student already belongs to a different active batch in the same program
    conflict = await db.scalar(
        select(BatchEnrollment)
        .join(Batch, BatchEnrollment.batch_id == Batch.id)
        .where(
            BatchEnrollment.user_id == user_id,
            Batch.program_id == batch.program_id,
            Batch.status == "active",
            BatchEnrollment.batch_id != batch_id,
        )
    )
    if conflict:
        raise StudentAlreadyInActiveBatch()

    program_enrollment = await _get_active_program_enrollment(
        db, user_id, batch.program_id, lock=True
    )

    be = BatchEnrollment(
        batch_id=batch_id,
        user_id=user_id,
        program_enrollment_id=program_enrollment.id,
    )
    db.add(be)
    await db.commit()

    result = await db.scalar(
        select(BatchEnrollment)
        .where(BatchEnrollment.id == be.id)
        .options(selectinload(BatchEnrollment.user))
    )
    return result  # type: ignore[return-value]


async def remove_member(
    db: AsyncSession,
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Remove a student from a batch.

    Raises:
        BatchNotFound: If the batch does not exist.
        BatchArchived: If the batch is archived.
        BatchEnrollmentNotFound: If the student is not a member of this batch.
    """
    batch = await _get_batch(db, batch_id)
    if batch.status == "archived":
        raise BatchArchived()

    be = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.batch_id == batch_id,
            BatchEnrollment.user_id == user_id,
        )
    )
    if not be:
        raise BatchEnrollmentNotFound()

    await db.delete(be)
    await db.commit()


async def list_members(
    db: AsyncSession,
    batch_id: uuid.UUID,
    skip: int,
    limit: int,
) -> tuple[list[BatchEnrollment], int]:
    """Return a paginated list of batch members with user info.

    Raises:
        BatchNotFound: If the batch does not exist.
    """
    await _get_batch(db, batch_id)

    base = select(BatchEnrollment).where(BatchEnrollment.batch_id == batch_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.options(selectinload(BatchEnrollment.user))
        .order_by(BatchEnrollment.enrolled_at.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.all()), total or 0


async def list_my_batches(
    db: AsyncSession,
    user_id: uuid.UUID,
    skip: int,
    limit: int,
) -> tuple[list[BatchEnrollment], int]:
    """Return a paginated list of the authenticated student's batch memberships."""
    base = select(BatchEnrollment).where(BatchEnrollment.user_id == user_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.options(selectinload(BatchEnrollment.batch))
        .order_by(BatchEnrollment.enrolled_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.all()), total or 0


async def list_available_batches_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[tuple[Batch, int]]:
    """Return eligible selectable batches for the student's active program."""
    active_program = await _get_current_active_program_enrollment(db, user_id)

    current_membership = await get_current_batch_for_user(db, user_id)
    if current_membership is not None:
        return []

    member_counts = (
        select(
            BatchEnrollment.batch_id.label("batch_id"),
            func.count(BatchEnrollment.id).label("member_count"),
        )
        .group_by(BatchEnrollment.batch_id)
        .subquery()
    )

    rows = await db.execute(
        select(
            Batch,
            func.coalesce(member_counts.c.member_count, 0).label("member_count"),
        )
        .outerjoin(member_counts, member_counts.c.batch_id == Batch.id)
        .where(
            Batch.program_id == active_program.program_id,
            Batch.status.in_(["upcoming", "active"]),
        )
        .order_by(Batch.starts_at.asc())
    )

    available: list[tuple[Batch, int]] = []
    now = datetime.now(UTC)
    for batch, member_count in rows.all():
        if not _is_batch_open_for_enrollment(batch, now=now):
            continue
        remaining = _remaining_seats(batch, int(member_count))
        if remaining <= 0:
            continue
        available.append((batch, remaining))

    return available


async def get_current_batch_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> BatchEnrollment | None:
    """Return the student's current batch membership for their active program."""
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()

    active_program = await db.scalar(
        select(ProgramEnrollment).where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.status == "active",
        )
    )
    if active_program is None:
        return None

    return await _get_current_batch_membership_for_program(
        db,
        user_id,
        active_program.program_id,
    )


async def select_batch_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> BatchEnrollment:
    """Assign the student to an eligible batch in their active program."""
    active_program = await _get_current_active_program_enrollment(db, user_id, lock=True)
    batch = await _get_batch_locked(db, batch_id)

    if batch.program_id != active_program.program_id:
        raise BatchProgramMismatch()
    if batch.status == "archived":
        raise BatchArchived()
    if not _is_batch_open_for_enrollment(batch):
        raise BatchNotOpenForEnrollment()

    if await _count_batch_members(db, batch_id) >= batch.capacity:
        raise BatchAtCapacity()

    existing = await db.scalar(
        select(BatchEnrollment).where(
            BatchEnrollment.batch_id == batch_id,
            BatchEnrollment.user_id == user_id,
        )
    )
    if existing:
        raise AlreadyInBatch()

    conflict = await db.scalar(
        select(BatchEnrollment)
        .join(Batch, BatchEnrollment.batch_id == Batch.id)
        .where(
            BatchEnrollment.user_id == user_id,
            Batch.program_id == active_program.program_id,
        )
        .limit(1)
    )
    if conflict:
        raise StudentAlreadyInProgramBatch()

    membership = BatchEnrollment(
        batch_id=batch_id,
        user_id=user_id,
        program_enrollment_id=active_program.id,
    )
    db.add(membership)
    await db.commit()

    result = await db.scalar(
        select(BatchEnrollment)
        .where(BatchEnrollment.id == membership.id)
        .options(selectinload(BatchEnrollment.batch))
    )
    return result  # type: ignore[return-value]


# ── Batch transfer requests ───────────────────────────────────────────────────

async def create_transfer_request(
    db: AsyncSession,
    user_id: uuid.UUID,
    to_batch_id: uuid.UUID,
    reason: str | None,
) -> BatchTransferRequest:
    """Create a new transfer request from the student's current batch."""
    active_program = await _get_current_active_program_enrollment(db, user_id, lock=True)
    current_membership = await _get_current_batch_membership_for_program(
        db,
        user_id,
        active_program.program_id,
        lock=True,
    )
    if current_membership is None:
        raise BatchTransferCurrentBatchRequired()

    target_batch = await _get_batch_locked(db, to_batch_id)

    if current_membership.batch_id == to_batch_id:
        raise BatchTransferSameBatch()
    if target_batch.program_id != active_program.program_id:
        raise BatchTransferProgramMismatch()
    if target_batch.status == "archived":
        raise BatchArchived()
    if not _is_batch_open_for_enrollment(target_batch):
        raise BatchNotOpenForEnrollment()
    if await _count_batch_members(db, to_batch_id) >= target_batch.capacity:
        raise BatchAtCapacity()

    existing_pending = await _get_pending_transfer_request_for_program(
        db,
        user_id,
        active_program.program_id,
    )
    if existing_pending is not None:
        raise BatchTransferRequestAlreadyPending()

    request = BatchTransferRequest(
        user_id=user_id,
        from_batch_id=current_membership.batch_id,
        to_batch_id=to_batch_id,
        status="pending",
        reason=reason,
    )
    db.add(request)
    await db.commit()
    return await _get_transfer_request_with_related(db, request.id)


async def list_my_transfer_requests(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[BatchTransferRequest]:
    """Return all transfer requests for the authenticated student."""
    rows = await db.scalars(
        select(BatchTransferRequest)
        .where(BatchTransferRequest.user_id == user_id)
        .options(
            selectinload(BatchTransferRequest.from_batch),
            selectinload(BatchTransferRequest.to_batch),
        )
        .order_by(BatchTransferRequest.created_at.desc())
    )
    return list(rows.all())


async def list_transfer_requests(
    db: AsyncSession,
    status: str | None,
    skip: int,
    limit: int,
) -> tuple[list[BatchTransferRequest], int]:
    """Return a paginated admin review queue for batch transfer requests."""
    base = select(BatchTransferRequest)
    if status is not None:
        base = base.where(BatchTransferRequest.status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.options(
            selectinload(BatchTransferRequest.user),
            selectinload(BatchTransferRequest.from_batch),
            selectinload(BatchTransferRequest.to_batch),
            selectinload(BatchTransferRequest.reviewer),
        )
        .order_by(BatchTransferRequest.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.all()), total or 0


async def approve_transfer_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    reviewer_id: uuid.UUID,
) -> BatchTransferRequest:
    """Approve a pending transfer request and move the student's membership."""
    request = await _get_batch_transfer_request_locked(db, request_id)
    if request.status != "pending":
        raise BatchTransferRequestAlreadyResolved()
    validate_transfer_request_transition(request.status, "approved")
    if request.to_batch_id is None:
        raise BatchNotFound()

    active_program = await _get_current_active_program_enrollment(db, request.user_id, lock=True)
    current_membership = await _get_current_batch_membership_for_program(
        db,
        request.user_id,
        active_program.program_id,
        lock=True,
    )
    if current_membership is None:
        raise BatchTransferCurrentBatchRequired()

    target_batch = await _get_batch_locked(db, request.to_batch_id)
    if target_batch.program_id != active_program.program_id:
        raise BatchTransferProgramMismatch()
    if current_membership.batch_id == target_batch.id:
        raise BatchTransferSameBatch()
    if target_batch.status == "archived":
        raise BatchArchived()
    if not _is_batch_open_for_enrollment(target_batch):
        raise BatchNotOpenForEnrollment()
    if await _count_batch_members(db, target_batch.id) >= target_batch.capacity:
        raise BatchAtCapacity()

    await db.delete(current_membership)
    await db.flush()

    db.add(
        BatchEnrollment(
            batch_id=target_batch.id,
            user_id=request.user_id,
            program_enrollment_id=active_program.id,
        )
    )
    request.status = "approved"
    request.reviewed_by = reviewer_id
    request.reviewed_at = datetime.now(UTC)

    await db.commit()
    return await _get_transfer_request_with_related(db, request.id)


async def deny_transfer_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    reviewer_id: uuid.UUID,
) -> BatchTransferRequest:
    """Deny a pending transfer request without changing batch membership."""
    request = await _get_batch_transfer_request_locked(db, request_id)
    if request.status != "pending":
        raise BatchTransferRequestAlreadyResolved()
    validate_transfer_request_transition(request.status, "denied")

    request.status = "denied"
    request.reviewed_by = reviewer_id
    request.reviewed_at = datetime.now(UTC)
    await db.commit()
    return await _get_transfer_request_with_related(db, request.id)


# ── Admin reporting (AL-BE-8) ─────────────────────────────────────────────────

async def get_batch_progress_report(
    db: AsyncSession,
    batch_id: uuid.UUID,
    skip: int,
    limit: int,
) -> tuple[list[BatchStudentProgressOut], int]:
    """Return a paginated per-student progress report for a batch.

    Executes 5 targeted GROUP BY queries for the page of students to avoid
    N+1 patterns:

    1. Load batch + program + ordered steps (with course titles).
    2. Paginate ``BatchEnrollment`` rows.
    3. Batch-fetch course enrollment status per ``(user_id, course_id)``.
    4. Batch-fetch total and completed lesson counts per ``(user_id, course_id)``.
    5. Batch-fetch best quiz score percentage per ``(user_id, course_id)``.
    6. Batch-fetch best published assignment score per ``(user_id, course_id)``.
    7. Assemble ``BatchStudentProgressOut`` rows in memory.

    Args:
        db: Async database session.
        batch_id: UUID of the batch to report on.
        skip: Offset for pagination.
        limit: Page size.

    Returns:
        A ``(list[BatchStudentProgressOut], total)`` tuple.

    Raises:
        BatchNotFound: When ``batch_id`` does not match any batch.
    """
    # 1. Load batch + program steps with course titles
    batch = await db.scalar(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(
            selectinload(Batch.program)
            .selectinload(Program.steps)
            .selectinload(ProgramStep.course)
        )
    )
    if batch is None:
        raise BatchNotFound()

    steps = sorted(batch.program.steps, key=lambda s: s.position)
    course_ids = [s.course_id for s in steps]

    # 2. Count + paginate BatchEnrollment rows with user loaded
    total = await db.scalar(
        select(func.count()).where(BatchEnrollment.batch_id == batch_id)
    ) or 0

    be_rows = list(
        await db.scalars(
            select(BatchEnrollment)
            .where(BatchEnrollment.batch_id == batch_id)
            .options(selectinload(BatchEnrollment.user))
            .order_by(BatchEnrollment.enrolled_at)
            .offset(skip)
            .limit(limit)
        )
    )

    if not be_rows:
        return [], total

    user_ids = [be.user_id for be in be_rows]

    # 3. Course enrollment status per (user_id, course_id)
    enr_rows = (
        await db.execute(
            select(Enrollment.user_id, Enrollment.course_id, Enrollment.status).where(
                Enrollment.user_id.in_(user_ids),
                Enrollment.course_id.in_(course_ids),
            )
        )
    ).all()
    enr_map: dict[tuple[uuid.UUID, uuid.UUID], str] = {
        (r.user_id, r.course_id): r.status for r in enr_rows
    }

    # 4a. Total lesson count per course
    total_lesson_rows = (
        await db.execute(
            select(Chapter.course_id, func.count(Lesson.id).label("cnt"))
            .join(Lesson, Lesson.chapter_id == Chapter.id)
            .where(Chapter.course_id.in_(course_ids))
            .group_by(Chapter.course_id)
        )
    ).all()
    total_lessons: dict[uuid.UUID, int] = {r.course_id: r.cnt for r in total_lesson_rows}

    # 4b. Completed lesson count per (user_id, course_id)
    completed_rows = (
        await db.execute(
            select(
                LessonProgress.user_id,
                Chapter.course_id,
                func.count(LessonProgress.id).label("cnt"),
            )
            .join(Lesson, Lesson.id == LessonProgress.lesson_id)
            .join(Chapter, Chapter.id == Lesson.chapter_id)
            .where(
                LessonProgress.user_id.in_(user_ids),
                Chapter.course_id.in_(course_ids),
                LessonProgress.status == "completed",
            )
            .group_by(LessonProgress.user_id, Chapter.course_id)
        )
    ).all()
    completed_map: dict[tuple[uuid.UUID, uuid.UUID], int] = {
        (r.user_id, r.course_id): r.cnt for r in completed_rows
    }

    # 5. Best quiz score percentage per (user_id, course_id)
    quiz_rows = (
        await db.execute(
            select(
                QuizSubmission.user_id,
                Chapter.course_id,
                func.max(
                    cast(QuizSubmission.score, SAFloat)
                    / cast(QuizSubmission.max_score, SAFloat)
                ).label("best_pct"),
            )
            .join(Quiz, Quiz.id == QuizSubmission.quiz_id)
            .join(Lesson, Lesson.id == Quiz.lesson_id)
            .join(Chapter, Chapter.id == Lesson.chapter_id)
            .where(
                QuizSubmission.user_id.in_(user_ids),
                Chapter.course_id.in_(course_ids),
                QuizSubmission.max_score > 0,
            )
            .group_by(QuizSubmission.user_id, Chapter.course_id)
        )
    ).all()
    quiz_map: dict[tuple[uuid.UUID, uuid.UUID], float] = {
        (r.user_id, r.course_id): r.best_pct for r in quiz_rows
    }

    # 6. Best published assignment score per (user_id, course_id)
    assign_rows = (
        await db.execute(
            select(
                AssignmentSubmission.user_id,
                Chapter.course_id,
                func.max(AssignmentSubmission.grade_score).label("best_score"),
            )
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
            .join(Lesson, Lesson.id == Assignment.lesson_id)
            .join(Chapter, Chapter.id == Lesson.chapter_id)
            .where(
                AssignmentSubmission.user_id.in_(user_ids),
                Chapter.course_id.in_(course_ids),
                AssignmentSubmission.grade_published_at.isnot(None),
            )
            .group_by(AssignmentSubmission.user_id, Chapter.course_id)
        )
    ).all()
    assign_map: dict[tuple[uuid.UUID, uuid.UUID], float] = {
        (r.user_id, r.course_id): r.best_score for r in assign_rows
    }

    # 7. Assemble per-student progress rows
    out: list[BatchStudentProgressOut] = []
    for be in be_rows:
        uid = be.user_id
        course_rows: list[StudentCourseProgressOut] = []
        required_pcts: list[float] = []

        for step in steps:
            cid = step.course_id
            total_l = total_lessons.get(cid, 0)
            completed_l = completed_map.get((uid, cid), 0)
            pct = (completed_l / total_l) if total_l > 0 else 0.0

            course_rows.append(
                StudentCourseProgressOut(
                    step_position=step.position,
                    course_id=cid,
                    course_title=step.course.title,
                    enrollment_status=enr_map.get((uid, cid)),
                    completion_pct=pct,
                    best_quiz_score_pct=quiz_map.get((uid, cid)),
                    latest_assignment_score=assign_map.get((uid, cid)),
                )
            )
            if step.is_required:
                required_pcts.append(pct)

        overall = sum(required_pcts) / len(required_pcts) if required_pcts else 0.0
        out.append(
            BatchStudentProgressOut(
                user_id=uid,
                email=be.user.email,
                display_name=be.user.display_name,
                batch_enrolled_at=be.enrolled_at,
                overall_completion_pct=overall,
                courses=course_rows,
            )
        )

    return out, total
