"""FastAPI router for program management, curriculum ordering, and program enrollment."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.program import Program
from app.db.models.user import User
from app.db.session import get_db
from app.modules.programs import service
from app.modules.programs.schemas import (
    PublicProgramOut,
    PublicProgramStepOut,
    ProgramEnrollmentAdminIn,
    ProgramEnrollmentOut,
    ProgramEnrollmentUpdateIn,
    ProgramIn,
    ProgramProgressOut,
    ProgramStepIn,
    ProgramStepOut,
    ProgramStepReorderIn,
    ProgramStepUpdateIn,
    ProgramStudentOut,
    ProgramUpdateIn,
    ProgramWithStepsOut,
    ProgramOut,
)

router = APIRouter(tags=["programs"])


def _to_public_program(program: Program) -> PublicProgramOut:
    """Flatten a program and its published course steps for public discovery."""
    public_steps = []
    for step in getattr(program, "steps", []):
        course = step.course
        if course is None or course.status != "published" or course.archived_at is not None:
            continue
        public_steps.append(
            PublicProgramStepOut(
                course_cover_image_url=course.cover_image_url,
                course_id=course.id,
                course_level=course.level,
                course_slug=course.slug,
                course_title=course.title,
                is_required=step.is_required,
                position=step.position,
            )
        )

    return PublicProgramOut(
        id=program.id,
        code=program.code,
        title=program.title,
        description=program.description,
        marketing_summary=program.marketing_summary,
        cover_image_url=program.cover_image_url,
        display_order=program.display_order,
        is_active=program.is_active,
        created_at=program.created_at,
        updated_at=program.updated_at,
        steps=public_steps,
    )


@router.get("/programs")
async def list_public_programs(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List active public programs ordered for marketing and discovery."""
    programs, total = await service.list_public_programs(db, skip=skip, limit=limit)
    return ok(
        [_to_public_program(program).model_dump() for program in programs],
        meta={"total": total, "skip": skip, "limit": limit},
    )


# ── Admin — program CRUD ───────────────────────────────────────────────────────

@router.post("/admin/programs", status_code=201)
async def create_program(
    body: ProgramIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Create a new program."""
    program = await service.create_program(
        db,
        code=body.code,
        title=body.title,
        description=body.description,
        marketing_summary=body.marketing_summary,
        cover_image_url=body.cover_image_url,
        display_order=body.display_order,
        is_active=body.is_active,
    )
    return ok(ProgramOut.model_validate(program).model_dump())


@router.get("/admin/programs")
async def list_programs(
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    is_active: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List programs, optionally filtered by active state."""
    programs, total = await service.list_programs(db, is_active=is_active, skip=skip, limit=limit)
    return ok(
        [ProgramOut.model_validate(p).model_dump() for p in programs],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.get("/admin/programs/{program_id}")
async def get_program(
    program_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Fetch a program with its ordered curriculum steps."""
    program = await service.get_program(db, program_id)
    return ok(ProgramWithStepsOut.model_validate(program).model_dump())


@router.get("/admin/programs/{program_id}/students")
async def list_program_students(
    program_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    batch_id: uuid.UUID | None = Query(None),
    subscription_status: str | None = Query(None),
    enrollment_status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Paginated roster of all students enrolled in a program.

    Supports filtering by batch membership, subscription status, and enrollment
    status.  Returns ``null`` for batch/subscription fields when the student has
    no assignment or billing record.

    Args:
        program_id: UUID of the target program.
        batch_id: Restrict to students in this batch.
        subscription_status: Filter by ``Subscription.status``
            (``"active"``, ``"past_due"``, ``"canceled"``, ``"trialing"``).
        enrollment_status: Filter by ``ProgramEnrollment.status``
            (``"active"``, ``"suspended"``, ``"completed"``, ``"canceled"``).
        skip: Offset for pagination.
        limit: Page size (max 200).
        db: Injected async database session.
        _: Admin role enforcement dependency.

    Returns:
        Paginated list of ``ProgramStudentOut`` with ``meta.total``,
        ``meta.skip``, and ``meta.limit``.
    """
    students, total = await service.list_program_students(
        db,
        program_id,
        batch_id=batch_id,
        subscription_status=subscription_status,
        enrollment_status=enrollment_status,
        skip=skip,
        limit=limit,
    )
    return ok(
        [s.model_dump() for s in students],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.patch("/admin/programs/{program_id}")
async def update_program(
    program_id: uuid.UUID,
    body: ProgramUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Partially update a program's metadata."""
    program = await service.update_program(
        db,
        program_id,
        title=body.title,
        description=body.description,
        marketing_summary=body.marketing_summary,
        cover_image_url=body.cover_image_url,
        display_order=body.display_order,
        is_active=body.is_active,
    )
    return ok(ProgramOut.model_validate(program).model_dump())


# ── Admin — curriculum steps ───────────────────────────────────────────────────

@router.post("/admin/programs/{program_id}/steps", status_code=201)
async def add_step(
    program_id: uuid.UUID,
    body: ProgramStepIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Add a course step to a program at the specified position."""
    step = await service.add_step(
        db,
        program_id=program_id,
        course_id=body.course_id,
        position=body.position,
        is_required=body.is_required,
    )
    return ok(ProgramStepOut.model_validate(step).model_dump())


@router.get("/admin/programs/{program_id}/steps")
async def list_steps(
    program_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """List all steps for a program ordered by position."""
    steps = await service.list_steps(db, program_id)
    return ok([ProgramStepOut.model_validate(s).model_dump() for s in steps])


@router.patch("/admin/programs/{program_id}/steps/{step_id}")
async def update_step(
    program_id: uuid.UUID,  # noqa: ARG001 — used for URL scoping clarity
    step_id: uuid.UUID,
    body: ProgramStepUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Partially update a curriculum step (position, course, or required flag)."""
    step = await service.update_step(
        db,
        step_id,
        course_id=body.course_id,
        position=body.position,
        is_required=body.is_required,
    )
    return ok(ProgramStepOut.model_validate(step).model_dump())


@router.delete("/admin/programs/{program_id}/steps/{step_id}", status_code=200)
async def delete_step(
    program_id: uuid.UUID,  # noqa: ARG001 — used for URL scoping clarity
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Remove a step from a program's curriculum."""
    await service.delete_step(db, step_id)
    return ok({"deleted": True})


@router.put("/admin/programs/{program_id}/steps/reorder")
async def reorder_steps(
    program_id: uuid.UUID,
    body: ProgramStepReorderIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Reorder all steps in a program.

    Supply the complete ordered list of step UUIDs.  Positions are assigned
    1..N from the given order.  Every existing step ID must be present.
    """
    steps = await service.reorder_steps(db, program_id, body.step_ids)
    return ok([ProgramStepOut.model_validate(s).model_dump() for s in steps])


# ── Admin — program enrollments ────────────────────────────────────────────────

@router.post("/admin/users/{user_id}/program-enrollments", status_code=201)
async def create_enrollment(
    user_id: uuid.UUID,
    body: ProgramEnrollmentAdminIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Enroll a student in a program.

    A student may only have one ``active`` enrollment at a time.  Creating a
    second active enrollment raises a 409 conflict.
    """
    enrollment = await service.create_enrollment(db, user_id=user_id, program_id=body.program_id)
    return ok(ProgramEnrollmentOut.model_validate(enrollment).model_dump())


@router.get("/admin/users/{user_id}/program-enrollments")
async def list_enrollments(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List all program enrollments for a student (all statuses, newest first)."""
    enrollments, total = await service.list_enrollments(db, user_id, skip=skip, limit=limit)
    return ok(
        [ProgramEnrollmentOut.model_validate(e).model_dump() for e in enrollments],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.patch("/admin/program-enrollments/{enrollment_id}")
async def update_enrollment(
    enrollment_id: uuid.UUID,
    body: ProgramEnrollmentUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = require_role(Role.ADMIN),
) -> dict:
    """Update the status of a program enrollment (e.g. suspend, complete, cancel)."""
    enrollment = await service.update_enrollment(db, enrollment_id, status=body.status)
    return ok(ProgramEnrollmentOut.model_validate(enrollment).model_dump())


# ── Student — active enrollment ────────────────────────────────────────────────

@router.get("/users/me/program-enrollment")
async def get_my_enrollment(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the authenticated student's current active program enrollment.

    Returns ``null`` if the student is not currently enrolled in any program.
    """
    enrollment = await service.get_active_enrollment(db, current_user.id)
    data = ProgramEnrollmentOut.model_validate(enrollment).model_dump() if enrollment else None
    return ok(data)


# ── Student — program progress ─────────────────────────────────────────────────

@router.get("/users/me/program-progress")
async def get_my_program_progress(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the full program progression summary for the authenticated student.

    Computes the current unlocked step and the accessible lesson list for that
    step.  Suitable for the dashboard summary ring and the player's routing
    logic.

    Returns ``403 PROGRAM_NOT_ACTIVE`` if the student has no active program
    enrollment.
    """
    progress = await service.get_program_progress(db, current_user.id)
    return ok(progress.model_dump())
