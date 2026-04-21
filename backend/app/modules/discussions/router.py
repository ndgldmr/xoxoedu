"""FastAPI router for lesson discussion thread endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.discussions import service
from app.modules.discussions.schemas import CreatePostIn, EditPostIn, FlagIn, ResolveFlagIn

router = APIRouter(tags=["discussions"])


# ── Thread CRUD ────────────────────────────────────────────────────────────────

@router.post("/lessons/{lesson_id}/discussions", status_code=201)
async def create_post(
    lesson_id: uuid.UUID,
    body: CreatePostIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
) -> dict:
    """Create a top-level discussion post or a reply in a lesson's thread.

    The requesting user must be enrolled in the course that owns this lesson
    (admins bypass the enrollment check).  Replies may only target top-level
    posts — nested replies beyond one level are rejected.
    """
    post = await service.create_post(
        db,
        current_user,
        lesson_id,
        body.body,
        body.parent_id,
    )
    return ok(post.model_dump())


@router.get("/lessons/{lesson_id}/discussions")
async def list_posts(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
    parent_id: uuid.UUID | None = Query(None, description="Fetch replies to this post ID"),
    cursor: str | None = Query(None, description="Opaque cursor from a previous page"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Return a paginated page of discussion posts for a lesson thread.

    With no ``parent_id``, returns top-level posts newest-first.  When
    ``parent_id`` is set, returns replies to that post oldest-first.
    Include the returned ``next_cursor`` as ``?cursor=`` in the next request
    to fetch the following page; a ``null`` cursor means no further pages exist.

    Each post includes ``upvote_count`` and ``viewer_has_upvoted`` reflecting
    the current user's vote state.
    """
    page = await service.list_posts(
        db,
        current_user,
        lesson_id,
        parent_id,
        cursor,
        limit,
    )
    return ok(
        [p.model_dump() for p in page.posts],
        meta={"next_cursor": page.next_cursor},
    )


@router.patch("/discussions/{post_id}")
async def edit_post(
    post_id: uuid.UUID,
    body: EditPostIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
) -> dict:
    """Edit the body of a discussion post.

    Students may only edit their own posts.  Admins may edit any post.
    Editing a soft-deleted post is rejected.
    """
    post = await service.edit_post(db, current_user, post_id, body.body)
    return ok(post.model_dump())


@router.delete("/discussions/{post_id}", status_code=200)
async def delete_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
) -> dict:
    """Soft-delete a discussion post.

    The post's body is replaced with a tombstone string and it remains
    in the thread so replies retain their context.  Students may only delete
    their own posts; admins may delete any post.
    """
    post = await service.delete_post(db, current_user, post_id)
    return ok(post.model_dump())


# ── Voting ─────────────────────────────────────────────────────────────────────

@router.post("/discussions/{post_id}/upvote", status_code=200)
async def toggle_upvote(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
) -> dict:
    """Toggle an upvote on a discussion post.

    Calling this endpoint when the user has not yet upvoted adds an upvote.
    Calling it again removes the upvote.  Authors cannot upvote their own posts.
    The response reflects the updated ``upvote_count`` and ``viewer_has_upvoted``
    state.
    """
    post = await service.toggle_upvote(db, current_user, post_id)
    return ok(post.model_dump())


# ── Flagging ───────────────────────────────────────────────────────────────────

@router.post("/discussions/{post_id}/flag", status_code=201)
async def flag_post(
    post_id: uuid.UUID,
    body: FlagIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT, Role.ADMIN),
) -> dict:
    """Flag a discussion post for moderation review.

    If the user already has an open flag on this post, the existing flag is
    updated with the new reason and context rather than creating a duplicate.
    Authors cannot flag their own posts.
    """
    flag = await service.flag_post(db, current_user, post_id, body.reason, body.context)
    return ok(flag.model_dump())


# ── Admin moderation queue ─────────────────────────────────────────────────────

@router.get("/admin/moderation/flags")
async def list_flags(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
    status: str | None = Query("open", description="Filter by flag status"),
    reason: str | None = Query(None, description="Filter by flag reason code"),
    cursor: str | None = Query(None, description="Opaque cursor from a previous page"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Return a paginated moderation flag queue (admin only).

    Defaults to showing only ``open`` flags.  Pass ``status=`` to filter by
    any status value, or omit it entirely by passing an empty string to see all
    flags.  Use ``reason=`` to further narrow by report category.
    """
    # Treat empty string as "no filter"
    status_filter = status if status else None
    page = await service.list_flags(db, status_filter, reason, cursor, limit)
    return ok(
        [f.model_dump() for f in page.flags],
        meta={"next_cursor": page.next_cursor},
    )


@router.post("/admin/moderation/flags/{flag_id}/resolve", status_code=200)
async def resolve_flag(
    flag_id: uuid.UUID,
    body: ResolveFlagIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.ADMIN),
) -> dict:
    """Resolve a moderation flag (admin only).

    The ``outcome`` must be one of ``dismissed``, ``content_removed``, or
    ``warned``.  A resolution note may be provided.  If the outcome is
    ``content_removed``, the flagged post is automatically soft-deleted.
    """
    flag = await service.resolve_flag(db, current_user, flag_id, body.outcome, body.resolution_note)
    return ok(flag.model_dump())
