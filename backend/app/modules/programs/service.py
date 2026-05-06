"""Business logic for programs, program steps, and program enrollments."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    CourseNotFound,
    DuplicateActiveProgramEnrollment,
    InvalidStatusTransition,
    ProgramEnrollmentNotFound,
    ProgramNotFound,
    ProgramNotActive,
    ProgramStepConflict,
    ProgramStepNotFound,
    UserNotFound,
)
from app.db.models.batch import Batch, BatchEnrollment
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.modules.programs.schemas import (
    VALID_ENROLLMENT_TRANSITIONS,
    AccessibleLessonOut,
    CurrentStepOut,
    ProgramProgressOut,
    ProgramStudentOut,
)
from app.modules.programs.unlock import (
    LessonInfo,
    StepInfo,
    compute_accessible_lessons,
    find_current_step,
)


# ── Program CRUD ───────────────────────────────────────────────────────────────

async def create_program(
    db: AsyncSession,
    *,
    code: str,
    title: str,
    description: str | None,
    marketing_summary: str | None,
    cover_image_url: str | None,
    display_order: int,
    is_active: bool,
) -> Program:
    """Create a new program.

    Args:
        db: Async database session.
        code: Short unique identifier (e.g. ``"PT"``).
        title: Human-readable program name.
        description: Optional long-form description.
        marketing_summary: Optional short public-facing summary.
        cover_image_url: Optional public-facing program image URL.
        display_order: Stable ordering index for listings.
        is_active: Whether the program participates in enrollment flows.

    Returns:
        The newly created ``Program`` instance.

    Raises:
        ProgramStepConflict: If a program with the given ``code`` already exists.
    """
    program = Program(
        code=code,
        title=title,
        description=description,
        marketing_summary=marketing_summary,
        cover_image_url=cover_image_url,
        display_order=display_order,
        is_active=is_active,
    )
    db.add(program)
    try:
        await db.commit()
        await db.refresh(program)
    except IntegrityError:
        await db.rollback()
        raise ProgramStepConflict(f"A program with code '{code}' already exists")
    return program


async def list_programs(
    db: AsyncSession,
    *,
    is_active: bool | None,
    skip: int,
    limit: int,
) -> tuple[list[Program], int]:
    """Return a paginated list of programs, optionally filtered by active state.

    Args:
        db: Async database session.
        is_active: If provided, restrict results to programs with this active state.
        skip: Number of records to skip.
        limit: Maximum number of records to return.

    Returns:
        A ``(programs, total)`` tuple.
    """
    base = select(Program)
    if is_active is not None:
        base = base.where(Program.is_active == is_active)
    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()
    result = await db.execute(
        base.order_by(Program.display_order.asc(), Program.code.asc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def get_program(db: AsyncSession, program_id: uuid.UUID) -> Program:
    """Fetch a single program with its ordered steps eagerly loaded.

    Args:
        db: Async database session.
        program_id: UUID of the program.

    Returns:
        The ``Program`` instance with ``steps`` loaded.

    Raises:
        ProgramNotFound: If no program with the given ID exists.
    """
    result = await db.execute(
        select(Program)
        .where(Program.id == program_id)
        .options(selectinload(Program.steps).selectinload(ProgramStep.course))
    )
    program = result.scalar_one_or_none()
    if program is None:
        raise ProgramNotFound()
    return program


async def update_program(
    db: AsyncSession,
    program_id: uuid.UUID,
    *,
    title: str | None,
    description: str | None,
    marketing_summary: str | None,
    cover_image_url: str | None,
    display_order: int | None,
    is_active: bool | None,
) -> Program:
    """Partially update a program's metadata.

    Args:
        db: Async database session.
        program_id: UUID of the program to update.
        title: New title, or ``None`` to leave unchanged.
        description: New description, or ``None`` to leave unchanged.
        marketing_summary: New short public summary, or ``None`` to leave unchanged.
        cover_image_url: New public-facing image URL, or ``None`` to leave unchanged.
        display_order: New stable ordering value, or ``None`` to leave unchanged.
        is_active: New active flag, or ``None`` to leave unchanged.

    Returns:
        The updated ``Program``.

    Raises:
        ProgramNotFound: If no program with the given ID exists.
    """
    program = await db.get(Program, program_id)
    if program is None:
        raise ProgramNotFound()
    if title is not None:
        program.title = title
    if description is not None:
        program.description = description
    if marketing_summary is not None:
        program.marketing_summary = marketing_summary
    if cover_image_url is not None:
        program.cover_image_url = cover_image_url
    if display_order is not None:
        program.display_order = display_order
    if is_active is not None:
        program.is_active = is_active
    await db.commit()
    await db.refresh(program)
    return program


async def list_public_programs(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
) -> tuple[list[Program], int]:
    """Return public active programs with course previews preloaded.

    The public catalog only exposes active programs. Their ordered steps are
    eagerly loaded together with the linked courses so the frontend can render
    a pathway view without issuing follow-up calls per program.
    """
    base = select(Program).where(Program.is_active.is_(True))
    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()
    result = await db.execute(
        base.options(selectinload(Program.steps).selectinload(ProgramStep.course))
        .order_by(Program.display_order.asc(), Program.code.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


# ── ProgramStep management ─────────────────────────────────────────────────────

async def add_step(
    db: AsyncSession,
    *,
    program_id: uuid.UUID,
    course_id: uuid.UUID,
    position: int,
    is_required: bool,
) -> ProgramStep:
    """Add a course step to a program at the given position.

    Args:
        db: Async database session.
        program_id: UUID of the program.
        course_id: UUID of the course to place at this step.
        position: 1-based curriculum index.
        is_required: Whether completion is required before advancing.

    Returns:
        The new ``ProgramStep``.

    Raises:
        ProgramNotFound: If the program does not exist.
        CourseNotFound: If the course does not exist.
        ProgramStepConflict: If the position or course is already taken in this program.
    """
    if await db.get(Program, program_id) is None:
        raise ProgramNotFound()
    if await db.get(Course, course_id) is None:
        raise CourseNotFound()
    step = ProgramStep(
        program_id=program_id,
        course_id=course_id,
        position=position,
        is_required=is_required,
    )
    db.add(step)
    try:
        await db.commit()
        await db.refresh(step)
    except IntegrityError:
        await db.rollback()
        raise ProgramStepConflict()
    return step


async def list_steps(db: AsyncSession, program_id: uuid.UUID) -> list[ProgramStep]:
    """Return all steps for a program ordered by position.

    Args:
        db: Async database session.
        program_id: UUID of the program.

    Returns:
        Ordered list of ``ProgramStep`` records.

    Raises:
        ProgramNotFound: If the program does not exist.
    """
    if await db.get(Program, program_id) is None:
        raise ProgramNotFound()
    result = await db.execute(
        select(ProgramStep)
        .where(ProgramStep.program_id == program_id)
        .order_by(ProgramStep.position)
    )
    return list(result.scalars().all())


async def update_step(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    course_id: uuid.UUID | None,
    position: int | None,
    is_required: bool | None,
) -> ProgramStep:
    """Partially update a program step.

    Args:
        db: Async database session.
        step_id: UUID of the step.
        course_id: New course, or ``None`` to leave unchanged.
        position: New position, or ``None`` to leave unchanged.
        is_required: New required flag, or ``None`` to leave unchanged.

    Returns:
        The updated ``ProgramStep``.

    Raises:
        ProgramStepNotFound: If the step does not exist.
        ProgramStepConflict: If the new position or course is already taken.
    """
    step = await db.get(ProgramStep, step_id)
    if step is None:
        raise ProgramStepNotFound()
    if course_id is not None:
        step.course_id = course_id
    if position is not None:
        step.position = position
    if is_required is not None:
        step.is_required = is_required
    try:
        await db.commit()
        await db.refresh(step)
    except IntegrityError:
        await db.rollback()
        raise ProgramStepConflict()
    return step


async def delete_step(db: AsyncSession, step_id: uuid.UUID) -> None:
    """Remove a step from its program.

    Args:
        db: Async database session.
        step_id: UUID of the step to delete.

    Raises:
        ProgramStepNotFound: If the step does not exist.
    """
    step = await db.get(ProgramStep, step_id)
    if step is None:
        raise ProgramStepNotFound()
    await db.delete(step)
    await db.commit()


async def reorder_steps(
    db: AsyncSession,
    program_id: uuid.UUID,
    step_ids: list[uuid.UUID],
) -> list[ProgramStep]:
    """Reassign positions 1..N for a program's steps in the given order.

    The caller must supply the IDs of **every** existing step — no more, no
    fewer.  Positions are assigned 1..N in the order of ``step_ids``.

    A two-phase write is used to avoid transient collisions on the
    ``uq_program_steps_program_position`` unique constraint: all steps are
    first moved to temporary negative offsets, then reassigned final values.

    Args:
        db: Async database session.
        program_id: UUID of the program whose steps are being reordered.
        step_ids: Full ordered list of step UUIDs.

    Returns:
        The reordered list of ``ProgramStep`` records.

    Raises:
        ProgramNotFound: If the program does not exist.
        ProgramStepConflict: If ``step_ids`` does not match the program's steps exactly.
    """
    if await db.get(Program, program_id) is None:
        raise ProgramNotFound()

    result = await db.execute(
        select(ProgramStep).where(ProgramStep.program_id == program_id)
    )
    existing_steps = {s.id: s for s in result.scalars().all()}

    provided_ids = set(step_ids)
    existing_ids = set(existing_steps.keys())
    if provided_ids != existing_ids:
        raise ProgramStepConflict(
            "step_ids must contain exactly the IDs of all existing steps in this program"
        )

    # Phase 1: move to negative offsets to avoid constraint collisions
    for idx, step_id in enumerate(step_ids):
        existing_steps[step_id].position = -(idx + 1)
    await db.flush()

    # Phase 2: assign final 1-based positions
    for idx, step_id in enumerate(step_ids):
        existing_steps[step_id].position = idx + 1
    await db.commit()

    for step in existing_steps.values():
        await db.refresh(step)

    return [existing_steps[sid] for sid in step_ids]


# ── ProgramEnrollment ──────────────────────────────────────────────────────────

async def create_enrollment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    program_id: uuid.UUID,
) -> ProgramEnrollment:
    """Enroll a student in a program.

    Only one ``active`` enrollment is allowed per student across all programs.
    If the student already has an active enrollment (in any program) this call
    raises ``DuplicateActiveProgramEnrollment``.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        program_id: UUID of the target program.

    Returns:
        The new ``ProgramEnrollment``.

    Raises:
        UserNotFound: If the student does not exist.
        ProgramNotFound: If the program does not exist.
        DuplicateActiveProgramEnrollment: If an active enrollment already exists.
        ProgramStepConflict: If the student is already enrolled in this specific program.
    """
    if await db.get(User, user_id) is None:
        raise UserNotFound()
    if await db.get(Program, program_id) is None:
        raise ProgramNotFound()

    active_check = await db.execute(
        select(ProgramEnrollment).where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.status == "active",
        )
    )
    if active_check.scalar_one_or_none() is not None:
        raise DuplicateActiveProgramEnrollment()

    enrollment = ProgramEnrollment(user_id=user_id, program_id=program_id, status="active")
    db.add(enrollment)
    try:
        await db.commit()
        await db.refresh(enrollment)
    except IntegrityError:
        await db.rollback()
        raise ProgramStepConflict("Student is already enrolled in this program")
    return enrollment


async def list_enrollments(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    skip: int,
    limit: int,
) -> tuple[list[ProgramEnrollment], int]:
    """Return all program enrollments for a student (all statuses, newest first).

    Args:
        db: Async database session.
        user_id: UUID of the student.
        skip: Records to skip.
        limit: Maximum records to return.

    Returns:
        A ``(enrollments, total)`` tuple.
    """
    base = select(ProgramEnrollment).where(ProgramEnrollment.user_id == user_id)
    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()
    result = await db.execute(
        base.order_by(ProgramEnrollment.enrolled_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def get_active_enrollment(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> ProgramEnrollment | None:
    """Return the student's current active program enrollment, if any.

    Args:
        db: Async database session.
        user_id: UUID of the student.

    Returns:
        The active ``ProgramEnrollment``, or ``None`` if the student is not
        currently enrolled in any program.
    """
    result = await db.execute(
        select(ProgramEnrollment).where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def update_enrollment(
    db: AsyncSession,
    enrollment_id: uuid.UUID,
    *,
    status: str,
) -> ProgramEnrollment:
    """Update the status of a program enrollment.

    Args:
        db: Async database session.
        enrollment_id: UUID of the enrollment.
        status: New status value; must be a valid transition from the current status.

    Returns:
        The updated ``ProgramEnrollment``.

    Raises:
        ProgramEnrollmentNotFound: If the enrollment does not exist.
        InvalidStatusTransition: If the transition is not allowed.
    """
    enrollment = await db.get(ProgramEnrollment, enrollment_id)
    if enrollment is None:
        raise ProgramEnrollmentNotFound()
    if status not in VALID_ENROLLMENT_TRANSITIONS.get(enrollment.status, set()):
        raise InvalidStatusTransition(
            f"Cannot transition from '{enrollment.status}' to '{status}'"
        )
    enrollment.status = status
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


# ── Program progress (AL-BE-7) ─────────────────────────────────────────────────

async def get_program_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> ProgramProgressOut:
    """Return the full program progression summary for a student.

    Computes the current unlocked step and the accessible lesson list for that
    step.  Intended for the dashboard summary ring and the player's routing
    logic.

    Args:
        db: Async database session.
        user_id: UUID of the student.

    Returns:
        A :class:`ProgramProgressOut` containing step counts, the current
        unlocked step, and per-lesson accessibility for the current step's
        course.  ``current_step`` is ``None`` when all steps are completed.

    Raises:
        ProgramNotActive: If the student has no active ``ProgramEnrollment``.
    """
    # 1. Active ProgramEnrollment with program → steps
    pe = await db.scalar(
        select(ProgramEnrollment)
        .where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.status == "active",
        )
        .options(
            selectinload(ProgramEnrollment.program).selectinload(Program.steps)
        )
    )
    if pe is None:
        raise ProgramNotActive()

    steps_sorted = sorted(pe.program.steps, key=lambda s: s.position)

    # 2. Enrollment rows for all step courses so we know completion state
    course_ids = [s.course_id for s in steps_sorted]
    enrollment_rows = await db.scalars(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id.in_(course_ids),
        )
    )
    enrollment_by_course: dict[uuid.UUID, Enrollment] = {
        e.course_id: e for e in enrollment_rows
    }

    # 3. Build StepInfo list and count completed steps
    step_infos = [
        StepInfo(
            step_id=s.id,
            course_id=s.course_id,
            position=s.position,
            is_required=s.is_required,
            course_enrollment_status=(
                enrollment_by_course[s.course_id].status
                if s.course_id in enrollment_by_course
                else None
            ),
        )
        for s in steps_sorted
    ]
    completed_steps = sum(
        1 for si in step_infos if si.course_enrollment_status == "completed"
    )

    # 4. Determine current step via pure unlock engine
    current_step_info = find_current_step(step_infos)
    if current_step_info is None:
        # All steps completed — program is finished
        return ProgramProgressOut(
            program_enrollment_id=pe.id,
            program_id=pe.program_id,
            program_title=pe.program.title,
            total_steps=len(step_infos),
            completed_steps=completed_steps,
            current_step=None,
        )

    # 5. Load current step's course with chapters and lessons
    course = await db.scalar(
        select(Course)
        .where(Course.id == current_step_info.course_id)
        .options(selectinload(Course.chapters).selectinload(Chapter.lessons))
    )

    # 6. Build chapter lookup to avoid lazy-load triggers on lesson.chapter
    chapter_by_lesson_id: dict[uuid.UUID, Chapter] = {}
    for ch in course.chapters:  # type: ignore[union-attr]
        for ls in ch.lessons:
            chapter_by_lesson_id[ls.id] = ch

    # 7. Flat ordered lesson list: (chapter.position ASC, lesson.position ASC)
    lessons_in_order: list[Lesson] = [
        ls
        for ch in sorted(course.chapters, key=lambda c: c.position)  # type: ignore[union-attr]
        for ls in sorted(ch.lessons, key=lambda l: l.position)
    ]
    lesson_ids = [ls.id for ls in lessons_in_order]

    # 8. Lesson progress rows for this course
    progress_rows = await db.scalars(
        select(LessonProgress).where(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id.in_(lesson_ids),
        )
    )
    progress_by_lesson: dict[uuid.UUID, LessonProgress] = {
        p.lesson_id: p for p in progress_rows
    }

    # 9. Build LessonInfo list and compute accessibility
    lesson_infos = [
        LessonInfo(
            lesson_id=ls.id,
            chapter_id=ls.chapter_id,
            chapter_title=chapter_by_lesson_id[ls.id].title,
            lesson_title=ls.title,
            position_in_course=idx,
            is_locked=ls.is_locked,
            progress_status=(
                progress_by_lesson[ls.id].status
                if ls.id in progress_by_lesson
                else "not_started"
            ),
            completed_at=(
                progress_by_lesson[ls.id].completed_at
                if ls.id in progress_by_lesson
                else None
            ),
        )
        for idx, ls in enumerate(lessons_in_order)
    ]
    results = compute_accessible_lessons(lesson_infos)

    # 10. Current course enrollment status
    current_enrollment = enrollment_by_course.get(current_step_info.course_id)
    enrollment_status = current_enrollment.status if current_enrollment else "active"

    current_step_out = CurrentStepOut(
        step_id=current_step_info.step_id,
        step_position=current_step_info.position,
        course_id=current_step_info.course_id,
        course_title=course.title,  # type: ignore[union-attr]
        course_slug=course.slug,  # type: ignore[union-attr]
        enrollment_status=enrollment_status,
        lessons=[
            AccessibleLessonOut(
                lesson_id=r.lesson_id,
                lesson_title=r.lesson_title,
                chapter_id=r.chapter_id,
                chapter_title=r.chapter_title,
                position_in_course=r.position_in_course,
                is_accessible=r.is_accessible,
                is_admin_locked=r.is_admin_locked,
                progress_status=r.progress_status,
                completed_at=r.completed_at,
            )
            for r in results
        ],
    )

    return ProgramProgressOut(
        program_enrollment_id=pe.id,
        program_id=pe.program_id,
        program_title=pe.program.title,
        total_steps=len(step_infos),
        completed_steps=completed_steps,
        current_step=current_step_out,
    )


# ── Admin reporting (AL-BE-8) ─────────────────────────────────────────────────

async def list_program_students(
    db: AsyncSession,
    program_id: uuid.UUID,
    *,
    batch_id: uuid.UUID | None,
    subscription_status: str | None,
    enrollment_status: str | None,
    skip: int,
    limit: int,
) -> tuple[list[ProgramStudentOut], int]:
    """Return a paginated roster of all students enrolled in a program.

    Joins ``ProgramEnrollment`` → ``User`` with optional LEFT OUTER JOINs to
    ``BatchEnrollment``/``Batch`` and ``Subscription`` so that students without
    a batch assignment or subscription still appear in the unfiltered result.

    Args:
        db: Async database session.
        program_id: UUID of the program to query.
        batch_id: When provided, restrict to students in this batch.
        subscription_status: When provided, filter by ``Subscription.status``.
        enrollment_status: When provided, filter by ``ProgramEnrollment.status``.
        skip: Offset for pagination.
        limit: Page size.

    Returns:
        A ``(list[ProgramStudentOut], total)`` tuple where ``total`` is the
        count before pagination.

    Raises:
        ProgramNotFound: When ``program_id`` does not match any program.
    """
    if await db.get(Program, program_id) is None:
        raise ProgramNotFound()

    stmt = (
        select(
            ProgramEnrollment.id.label("enrollment_id"),
            ProgramEnrollment.status.label("enrollment_status"),
            ProgramEnrollment.enrolled_at,
            ProgramEnrollment.completed_at,
            User.id.label("user_id"),
            User.email,
            User.display_name,
            User.username,
            Batch.id.label("batch_id"),
            Batch.title.label("batch_title"),
            Subscription.status.label("subscription_status"),
        )
        .select_from(ProgramEnrollment)
        .join(User, User.id == ProgramEnrollment.user_id)
        .outerjoin(
            BatchEnrollment,
            (BatchEnrollment.user_id == ProgramEnrollment.user_id)
            & (BatchEnrollment.program_enrollment_id == ProgramEnrollment.id),
        )
        .outerjoin(Batch, Batch.id == BatchEnrollment.batch_id)
        .outerjoin(Subscription, Subscription.user_id == ProgramEnrollment.user_id)
        .where(ProgramEnrollment.program_id == program_id)
    )

    if enrollment_status is not None:
        stmt = stmt.where(ProgramEnrollment.status == enrollment_status)
    if batch_id is not None:
        stmt = stmt.where(Batch.id == batch_id)
    if subscription_status is not None:
        stmt = stmt.where(Subscription.status == subscription_status)

    total = await db.scalar(
        select(func.count()).select_from(stmt.subquery())
    ) or 0

    rows = (
        await db.execute(
            stmt.order_by(ProgramEnrollment.enrolled_at.desc())
            .offset(skip)
            .limit(limit)
        )
    ).all()

    return [
        ProgramStudentOut(
            enrollment_id=r.enrollment_id,
            enrollment_status=r.enrollment_status,
            enrolled_at=r.enrolled_at,
            completed_at=r.completed_at,
            user_id=r.user_id,
            email=r.email,
            display_name=r.display_name,
            username=r.username,
            batch_id=r.batch_id,
            batch_title=r.batch_title,
            subscription_status=r.subscription_status,
        )
        for r in rows
    ], total
