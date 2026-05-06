"""API router for placement test retrieval, submission, and admin management."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.session import get_db
from app.modules.placement import service
from app.modules.placement.schemas import PlacementAttemptIn, PlacementResultOverrideIn

router = APIRouter(tags=["placement"])


# ── Student endpoints ──────────────────────────────────────────────────────────

@router.get("/placement-tests/current")
async def get_current_placement_test(
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """Return the active versioned placement test definition.

    Correct answers are never included in the response.

    Args:
        db: Injected async database session.
        current_user: Authenticated user from the JWT.

    Returns:
        A ``PlacementTestOut`` wrapped in the standard response envelope.
    """
    test = await service.get_active_placement_test(db)
    return ok(test.model_dump())


@router.post("/placement-attempts", status_code=201)
async def submit_placement_attempt(
    data: PlacementAttemptIn,
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """Submit a placement attempt and receive the scored result.

    Scores the answers, maps them to a diagnostic band, persists the attempt
    and result rows, and creates or reactivates the student's program enrollment.

    Args:
        data: Student's answers and optional per-question timing.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        A ``PlacementAttemptOut`` with score, band, and assigned program,
        wrapped in the standard response envelope.
    """
    result = await service.submit_placement_attempt(db, current_user.id, data)
    return ok(result.model_dump())


@router.get("/users/me/placement-result")
async def get_my_placement_result(
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """Return the current student's most recent placement result.

    Args:
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        A ``PlacementResultOut`` wrapped in the standard response envelope.

    Raises:
        NoPlacementResult (404): When the student has not completed the assessment.
    """
    result = await service.get_my_placement_result(db, current_user.id)
    return ok(result.model_dump())


# ── Admin endpoints ────────────────────────────────────────────────────────────

@router.get("/admin/placement-results")
async def list_placement_results(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    program_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _=require_role(Role.ADMIN),
) -> dict:
    """Return a paginated list of all placement results.

    Args:
        page: 1-based page number (default 1).
        size: Results per page (default 50, max 200).
        program_id: Optional — restrict to results for a specific program.
        db: Injected async database session.
        _: Admin role enforcement dependency.

    Returns:
        A paginated list of ``AdminPlacementResultOut`` objects with
        ``meta.total``, ``meta.page``, and ``meta.size`` in the envelope.
    """
    results, total = await service.list_placement_results(
        db, page=page, size=size, program_id=program_id
    )
    return ok(
        [r.model_dump() for r in results],
        meta={"total": total, "page": page, "size": size},
    )


@router.patch("/admin/placement-results/{result_id}")
async def override_placement_result(
    result_id: uuid.UUID,
    data: PlacementResultOverrideIn,
    db: AsyncSession = Depends(get_db),
    _=require_role(Role.ADMIN),
) -> dict:
    """Override a placement result with an admin-assigned program and level.

    Sets ``is_override=True`` on the result and swaps the student's active
    program enrollment.  The original attempt data is preserved.

    Args:
        result_id: UUID of the ``PlacementResult`` to override.
        data: New program UUID and diagnostic level label.
        db: Injected async database session.
        _: Admin role enforcement dependency.

    Returns:
        The updated ``AdminPlacementResultOut`` wrapped in the standard
        response envelope.

    Raises:
        PlacementResultNotFound (404): When no result with ``result_id`` exists.
        ProgramNotFound (404): When ``data.program_id`` does not match any program.
    """
    result = await service.override_placement_result(db, result_id, data)
    return ok(result.model_dump())
