"""Business logic for lesson discussion threads, voting, and moderation."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.orm import aliased, selectinload

from app.core.exceptions import (
    CannotFlagOwnPost,
    CannotVoteOnOwnPost,
    DiscussionFlagAlreadyResolved,
    DiscussionFlagNotFound,
    DiscussionPostForbidden,
    DiscussionPostNotFound,
    LessonNotFound,
    NotEnrolled,
)
from app.db.models.course import Chapter, Lesson
from app.db.models.discussion import DiscussionFlag, DiscussionPost, DiscussionPostVote
from app.db.models.enrollment import Enrollment
from app.db.models.user import User
from app.modules.discussions.mentions import extract_mentions
from app.modules.discussions.schemas import (
    AuthorOut,
    DiscussionFlagOut,
    DiscussionPostOut,
    FlagPageOut,
    ThreadPageOut,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Body text substituted into a soft-deleted post.
TOMBSTONE = "[deleted]"

# Maximum nesting depth: replies may only target top-level posts.
_MAX_DEPTH = 1


# ── Cursor helpers ─────────────────────────────────────────────────────────────

def encode_cursor(created_at: datetime, post_id: uuid.UUID) -> str:
    """Encode a ``(created_at, post_id)`` pair as an opaque URL-safe cursor.

    Args:
        created_at: The post's creation timestamp (timezone-aware).
        post_id: The post's UUID primary key.

    Returns:
        A URL-safe base64 string that can be passed back as ``?cursor=``.
    """
    payload = f"{created_at.isoformat()}|{post_id}"
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode an opaque cursor back to ``(created_at, post_id)``.

    Args:
        cursor: The cursor string previously produced by :func:`encode_cursor`.

    Returns:
        A ``(datetime, UUID)`` tuple.

    Raises:
        ValueError: If the cursor cannot be decoded or parsed.
    """
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = payload.split("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except Exception as exc:
        raise ValueError(f"Invalid cursor: {cursor!r}") from exc


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _get_lesson_course_id(db: AsyncSession, lesson_id: uuid.UUID) -> uuid.UUID:
    """Return the course_id for a lesson or raise ``LessonNotFound``.

    Args:
        db: Async database session.
        lesson_id: UUID of the target lesson.

    Returns:
        The ``course_id`` that owns this lesson.

    Raises:
        LessonNotFound: If no lesson with that ID exists.
    """
    row = await db.execute(
        select(Lesson.id, Chapter.course_id)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .where(Lesson.id == lesson_id)
    )
    result = row.first()
    if result is None:
        raise LessonNotFound()
    return result.course_id


async def _require_lesson_access(
    db: AsyncSession, user: User, lesson_id: uuid.UUID
) -> None:
    """Verify that *user* has read/write access to the lesson's discussion.

    Admins always pass.  Students must have an active or completed enrollment
    in the course that owns this lesson.

    Args:
        db: Async database session.
        user: The authenticated user requesting access.
        lesson_id: UUID of the lesson whose thread is being accessed.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not enrolled in the lesson's course.
    """
    course_id = await _get_lesson_course_id(db, lesson_id)
    if user.role == "admin":
        return
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user.id,
            Enrollment.course_id == course_id,
            Enrollment.status.in_(["active", "completed"]),
        )
    )
    if not enrollment:
        raise NotEnrolled()


async def _get_post_or_404(
    db: AsyncSession, post_id: uuid.UUID
) -> DiscussionPost:
    """Fetch a discussion post by ID or raise ``DiscussionPostNotFound``.

    Args:
        db: Async database session.
        post_id: UUID of the post to fetch.

    Returns:
        The ``DiscussionPost`` ORM instance.

    Raises:
        DiscussionPostNotFound: If no post with that ID exists.
    """
    post = await db.get(DiscussionPost, post_id)
    if post is None:
        raise DiscussionPostNotFound()
    return post


async def _get_vote_data(
    db: AsyncSession, post_id: uuid.UUID, viewer_id: uuid.UUID
) -> tuple[int, bool]:
    """Return ``(upvote_count, viewer_has_upvoted)`` for a single post.

    Args:
        db: Async database session.
        post_id: UUID of the post to query.
        viewer_id: UUID of the requesting user.

    Returns:
        A tuple of ``(total_upvotes, True_if_viewer_voted)``.
    """
    count: int = await db.scalar(
        select(func.count(DiscussionPostVote.id)).where(
            DiscussionPostVote.post_id == post_id
        )
    ) or 0
    voted = await db.scalar(
        select(DiscussionPostVote.id).where(
            DiscussionPostVote.post_id == post_id,
            DiscussionPostVote.user_id == viewer_id,
        )
    )
    return count, voted is not None


async def _batch_voted_ids(
    db: AsyncSession, post_ids: list[uuid.UUID], viewer_id: uuid.UUID
) -> set[uuid.UUID]:
    """Return the subset of *post_ids* that *viewer_id* has upvoted.

    Uses a single ``IN`` query to avoid N+1 per-post vote-state lookups.

    Args:
        db: Async database session.
        post_ids: List of post UUIDs to check.
        viewer_id: UUID of the requesting user.

    Returns:
        A set of post UUIDs from *post_ids* that the viewer has upvoted.
    """
    if not post_ids:
        return set()
    rows = await db.execute(
        select(DiscussionPostVote.post_id).where(
            DiscussionPostVote.post_id.in_(post_ids),
            DiscussionPostVote.user_id == viewer_id,
        )
    )
    return {row[0] for row in rows}


def _build_post_out(
    post: DiscussionPost,
    reply_count: int,
    upvote_count: int = 0,
    viewer_has_upvoted: bool = False,
) -> DiscussionPostOut:
    """Construct a ``DiscussionPostOut`` DTO from an ORM instance and computed fields.

    Args:
        post: The ``DiscussionPost`` ORM instance (author must be loaded).
        reply_count: Pre-computed number of non-deleted replies.
        upvote_count: Total upvotes on this post.
        viewer_has_upvoted: Whether the requesting user has upvoted this post.

    Returns:
        A serialisable ``DiscussionPostOut`` schema instance.
    """
    return DiscussionPostOut(
        id=post.id,
        lesson_id=post.lesson_id,
        parent_id=post.parent_id,
        body=post.body,
        is_deleted=post.deleted_at is not None,
        edited_at=post.edited_at,
        created_at=post.created_at,
        author=AuthorOut(
            id=post.author.id,
            username=post.author.username,
            display_name=post.author.display_name,
            avatar_url=post.author.avatar_url,
        ),
        reply_count=reply_count,
        upvote_count=upvote_count,
        viewer_has_upvoted=viewer_has_upvoted,
        mentions=extract_mentions(post.body) if post.deleted_at is None else [],
    )


def _build_flag_out(flag: DiscussionFlag) -> DiscussionFlagOut:
    """Construct a ``DiscussionFlagOut`` DTO from an ORM instance.

    Args:
        flag: The ``DiscussionFlag`` ORM instance (reporter must be loaded).

    Returns:
        A serialisable ``DiscussionFlagOut`` schema instance.
    """
    return DiscussionFlagOut(
        id=flag.id,
        post_id=flag.post_id,
        reason=flag.reason,
        context=flag.context,
        status=flag.status,
        reporter=AuthorOut(
            id=flag.reporter.id,
            username=flag.reporter.username,
            display_name=flag.reporter.display_name,
            avatar_url=flag.reporter.avatar_url,
        ),
        resolved_by_id=flag.resolved_by,
        resolved_at=flag.resolved_at,
        resolution_note=flag.resolution_note,
        created_at=flag.created_at,
    )


# ── Query builder ──────────────────────────────────────────────────────────────

async def _fetch_page(
    db: AsyncSession,
    lesson_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[tuple[DiscussionPost, int, int]], bool]:
    """Fetch one page of posts and report whether more pages exist.

    Uses correlated scalar subqueries for reply counts and upvote counts to
    avoid N+1 queries.  Ordering is deterministic: top-level posts
    newest-first ``(created_at DESC, id DESC)``; replies oldest-first
    ``(created_at ASC, id ASC)``.

    Args:
        db: Async database session.
        lesson_id: Lesson whose thread is being listed.
        parent_id: ``None`` for top-level posts; a UUID to fetch replies.
        cursor: Opaque cursor from a previous page response.
        limit: Maximum number of posts to return in this page.

    Returns:
        A tuple of ``(rows, has_more)`` where *rows* is a list of
        ``(DiscussionPost, reply_count, upvote_count)`` tuples and
        *has_more* indicates whether further pages exist.
    """
    reply_alias = aliased(DiscussionPost, name="reply_alias")
    reply_count_sq = (
        select(func.count())
        .select_from(reply_alias)
        .where(reply_alias.parent_id == DiscussionPost.id)
        .where(reply_alias.deleted_at.is_(None))
        .correlate(DiscussionPost)
        .scalar_subquery()
    )

    upvote_count_sq = (
        select(func.count())
        .select_from(DiscussionPostVote)
        .where(DiscussionPostVote.post_id == DiscussionPost.id)
        .correlate(DiscussionPost)
        .scalar_subquery()
    )

    is_top_level = parent_id is None

    stmt = (
        select(
            DiscussionPost,
            reply_count_sq.label("reply_count"),
            upvote_count_sq.label("upvote_count"),
        )
        .options(selectinload(DiscussionPost.author))
        .where(DiscussionPost.lesson_id == lesson_id)
        .where(
            DiscussionPost.parent_id.is_(None)
            if is_top_level
            else DiscussionPost.parent_id == parent_id
        )
    )

    if cursor is not None:
        cur_ts, cur_id = decode_cursor(cursor)
        if is_top_level:
            # Newest-first: next page = older rows
            stmt = stmt.where(
                sa.or_(
                    DiscussionPost.created_at < cur_ts,
                    sa.and_(
                        DiscussionPost.created_at == cur_ts,
                        DiscussionPost.id < cur_id,
                    ),
                )
            )
        else:
            # Oldest-first: next page = newer rows
            stmt = stmt.where(
                sa.or_(
                    DiscussionPost.created_at > cur_ts,
                    sa.and_(
                        DiscussionPost.created_at == cur_ts,
                        DiscussionPost.id > cur_id,
                    ),
                )
            )

    if is_top_level:
        stmt = stmt.order_by(DiscussionPost.created_at.desc(), DiscussionPost.id.desc())
    else:
        stmt = stmt.order_by(DiscussionPost.created_at.asc(), DiscussionPost.id.asc())

    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = result.all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return [(row[0], row[1], row[2]) for row in page_rows], has_more


# ── Public service functions — thread CRUD ─────────────────────────────────────

async def list_posts(
    db: AsyncSession,
    user: User,
    lesson_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    cursor: str | None,
    limit: int,
) -> ThreadPageOut:
    """Return a paginated page of discussion posts for a lesson thread.

    Top-level posts (``parent_id=None``) are returned newest-first.  Replies
    to a specific parent are returned oldest-first.

    Args:
        db: Async database session.
        user: Authenticated user requesting the thread.
        lesson_id: UUID of the lesson whose thread to list.
        parent_id: ``None`` to list top-level posts; a UUID to list replies.
        cursor: Opaque cursor from the previous page; ``None`` for the first page.
        limit: Maximum number of posts per page.

    Returns:
        A ``ThreadPageOut`` with the post list and a ``next_cursor`` (or ``None``).

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not enrolled in the lesson's course.
    """
    await _require_lesson_access(db, user, lesson_id)
    triples, has_more = await _fetch_page(db, lesson_id, parent_id, cursor, limit)

    post_ids = [post.id for post, _, _ in triples]
    voted_ids = await _batch_voted_ids(db, post_ids, user.id)

    posts = [
        _build_post_out(post, reply_count, upvote_count, post.id in voted_ids)
        for post, reply_count, upvote_count in triples
    ]

    next_cursor: str | None = None
    if has_more and triples:
        last_post, _, _ = triples[-1]
        next_cursor = encode_cursor(last_post.created_at, last_post.id)

    return ThreadPageOut(posts=posts, next_cursor=next_cursor)


async def create_post(
    db: AsyncSession,
    user: User,
    lesson_id: uuid.UUID,
    body: str,
    parent_id: uuid.UUID | None,
) -> DiscussionPostOut:
    """Create a new top-level post or reply in a lesson's discussion thread.

    Replies are only allowed to target top-level posts (one level of nesting).
    The parent must be in the same lesson and must not be soft-deleted.

    Args:
        db: Async database session.
        user: Authenticated user creating the post.
        lesson_id: UUID of the lesson this post belongs to.
        body: Post text content.
        parent_id: UUID of the post being replied to; ``None`` for top-level.

    Returns:
        The newly created post as a ``DiscussionPostOut``.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not enrolled in the lesson's course.
        DiscussionPostNotFound: If the specified parent does not exist.
        DiscussionPostForbidden: If the parent is in a different lesson, is
            already deleted, or is itself a reply (depth > 1).
    """
    await _require_lesson_access(db, user, lesson_id)

    parent: DiscussionPost | None = None
    if parent_id is not None:
        parent = await _get_post_or_404(db, parent_id)
        if parent.lesson_id != lesson_id:
            raise DiscussionPostForbidden("Parent post is not in this lesson")
        if parent.deleted_at is not None:
            raise DiscussionPostForbidden("Cannot reply to a deleted post")
        if parent.parent_id is not None:
            raise DiscussionPostForbidden("Replies to replies are not supported")

    post = DiscussionPost(
        lesson_id=lesson_id,
        author_id=user.id,
        parent_id=parent_id,
        body=body,
    )
    db.add(post)
    await db.flush()

    from app.modules.notifications import service as notification_service

    pending_notifications = []

    if parent is not None and parent.author_id != user.id:
        reply_notif = notification_service.build_discussion_reply_notification(
            recipient_id=parent.author_id,
            actor=user,
            lesson_id=lesson_id,
            parent_post_id=parent.id,
            reply_post_id=post.id,
            reply_body=body,
        )
        db.add(reply_notif)
        pending_notifications.append(reply_notif)

    mentioned_usernames = extract_mentions(body)
    if mentioned_usernames:
        mentioned_users = (
            await db.scalars(select(User).where(User.username.in_(mentioned_usernames)))
        ).all()
        mentioned_by_username = {
            mentioned_user.username: mentioned_user for mentioned_user in mentioned_users
        }
        for mentioned_username in mentioned_usernames:
            mentioned_user = mentioned_by_username.get(mentioned_username)
            if mentioned_user is None or mentioned_user.id == user.id:
                continue
            mention_notif = notification_service.build_mention_notification(
                recipient_id=mentioned_user.id,
                actor=user,
                lesson_id=lesson_id,
                post_id=post.id,
                post_body=body,
                mentioned_username=mentioned_username,
            )
            db.add(mention_notif)
            pending_notifications.append(mention_notif)

    # Flush to populate server timestamps before building serializable DTOs.
    # DTOs are built here, pre-commit, because SQLAlchemy expires non-PK columns
    # on commit and accessing them afterwards triggers unwanted lazy loads.
    if pending_notifications:
        await db.flush()
    notif_delivery_info = [
        (n.id, n.recipient_id, n.type, notification_service.notification_to_out(n))
        for n in pending_notifications
    ]

    await db.commit()

    if notif_delivery_info:
        from app.core.redis import get_redis

        redis = get_redis()
        for notif_id, recipient_id, notification_type, notif_out in notif_delivery_info:
            await notification_service.dispatch_notification_delivery(
                db,
                notification_id=notif_id,
                recipient_id=recipient_id,
                notification_type=notification_type,
                notification_out=notif_out,
                redis=redis,
            )
    await db.refresh(post)

    # Load author for response DTO
    await db.refresh(post, ["author"])

    return _build_post_out(post, reply_count=0, upvote_count=0, viewer_has_upvoted=False)


async def edit_post(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
    body: str,
) -> DiscussionPostOut:
    """Update the body of a discussion post (own posts only).

    Args:
        db: Async database session.
        user: Authenticated user making the edit.
        post_id: UUID of the post to edit.
        body: The new post body text.

    Returns:
        The updated post as a ``DiscussionPostOut``.

    Raises:
        DiscussionPostNotFound: If the post does not exist.
        DiscussionPostForbidden: If the post is already deleted or the user
            is not the author (non-admins).
    """
    post = await _get_post_or_404(db, post_id)

    if post.deleted_at is not None:
        raise DiscussionPostForbidden("Cannot edit a deleted post")
    if user.role != "admin" and post.author_id != user.id:
        raise DiscussionPostForbidden("You can only edit your own posts")

    post.body = body
    post.edited_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(post, ["author"])

    count: int = await db.scalar(
        select(func.count(DiscussionPost.id)).where(
            DiscussionPost.parent_id == post.id,
            DiscussionPost.deleted_at.is_(None),
        )
    ) or 0
    upvote_count, viewer_has_upvoted = await _get_vote_data(db, post_id, user.id)

    return _build_post_out(
        post,
        reply_count=count,
        upvote_count=upvote_count,
        viewer_has_upvoted=viewer_has_upvoted,
    )


async def delete_post(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
) -> DiscussionPostOut:
    """Soft-delete a discussion post.

    The post's ``body`` is replaced with the tombstone string and
    ``deleted_at`` is stamped.  Replies remain visible and intact.
    Only the post's author may delete their own post; admins may delete any post.

    Args:
        db: Async database session.
        user: Authenticated user requesting the delete.
        post_id: UUID of the post to soft-delete.

    Returns:
        The tombstoned post as a ``DiscussionPostOut``.

    Raises:
        DiscussionPostNotFound: If the post does not exist.
        DiscussionPostForbidden: If the post is already deleted or the user
            is neither the author nor an admin.
    """
    post = await _get_post_or_404(db, post_id)

    if post.deleted_at is not None:
        raise DiscussionPostForbidden("Post is already deleted")
    if user.role != "admin" and post.author_id != user.id:
        raise DiscussionPostForbidden("You can only delete your own posts")

    post.body = TOMBSTONE
    post.deleted_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(post, ["author"])

    count: int = await db.scalar(
        select(func.count(DiscussionPost.id)).where(
            DiscussionPost.parent_id == post.id,
            DiscussionPost.deleted_at.is_(None),
        )
    ) or 0
    upvote_count, viewer_has_upvoted = await _get_vote_data(db, post_id, user.id)

    return _build_post_out(
        post,
        reply_count=count,
        upvote_count=upvote_count,
        viewer_has_upvoted=viewer_has_upvoted,
    )


# ── Public service functions — voting ──────────────────────────────────────────

async def set_upvote(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
    *,
    upvoted: bool,
) -> DiscussionPostOut:
    """Set the current user's upvote on a discussion post idempotently.

    Authors may not vote on their own posts.

    Args:
        db: Async database session.
        user: Authenticated user changing the vote.
        post_id: UUID of the post to upvote or remove an upvote from.
        upvoted: Desired vote state.

    Returns:
        The updated post DTO reflecting the new vote totals.

    Raises:
        DiscussionPostNotFound: If the post does not exist.
        CannotVoteOnOwnPost: If the user attempts to vote on their own post.
    """
    post = await _get_post_or_404(db, post_id)

    if post.author_id == user.id:
        raise CannotVoteOnOwnPost()

    existing = await db.scalar(
        select(DiscussionPostVote).where(
            DiscussionPostVote.post_id == post_id,
            DiscussionPostVote.user_id == user.id,
        )
    )

    if upvoted and existing is None:
        db.add(DiscussionPostVote(post_id=post_id, user_id=user.id))
    elif not upvoted and existing is not None:
        await db.delete(existing)

    await db.commit()
    await db.refresh(post, ["author"])

    count: int = await db.scalar(
        select(func.count(DiscussionPost.id)).where(
            DiscussionPost.parent_id == post.id,
            DiscussionPost.deleted_at.is_(None),
        )
    ) or 0
    upvote_count, viewer_has_upvoted = await _get_vote_data(db, post_id, user.id)

    return _build_post_out(
        post,
        reply_count=count,
        upvote_count=upvote_count,
        viewer_has_upvoted=viewer_has_upvoted,
    )


async def toggle_upvote(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
) -> DiscussionPostOut:
    """Toggle the current user's upvote on a discussion post."""
    existing = await db.scalar(
        select(DiscussionPostVote).where(
            DiscussionPostVote.post_id == post_id,
            DiscussionPostVote.user_id == user.id,
        )
    )
    return await set_upvote(
        db,
        user,
        post_id,
        upvoted=existing is None,
    )


# ── Public service functions — flagging ────────────────────────────────────────

async def flag_post(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
    reason: str,
    context: str | None,
) -> DiscussionFlagOut:
    """Create or update an open moderation flag on a discussion post.

    If the user already has an open flag on this post, its ``reason`` and
    ``context`` are updated in-place.  Otherwise a new flag is created.
    The partial unique index on ``(post_id, reporter_id) WHERE status='open'``
    provides a DB-level safety net against concurrent duplicate inserts.

    Args:
        db: Async database session.
        user: Authenticated user raising the flag.
        post_id: UUID of the post to flag.
        reason: Categorisation code for the report.
        context: Optional free-text context note.

    Returns:
        The created or updated ``DiscussionFlagOut`` DTO.

    Raises:
        DiscussionPostNotFound: If the post does not exist.
        CannotFlagOwnPost: If the user attempts to flag their own post.
    """
    post = await _get_post_or_404(db, post_id)

    if post.author_id == user.id:
        raise CannotFlagOwnPost()

    existing = await db.scalar(
        select(DiscussionFlag).where(
            DiscussionFlag.post_id == post_id,
            DiscussionFlag.reporter_id == user.id,
            DiscussionFlag.status == "open",
        )
    )

    if existing is not None:
        existing.reason = reason
        existing.context = context
        await db.commit()
        await db.refresh(existing, ["reporter"])
        return _build_flag_out(existing)

    flag = DiscussionFlag(
        post_id=post_id,
        reporter_id=user.id,
        reason=reason,
        context=context,
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag, ["reporter"])
    return _build_flag_out(flag)


# ── Public service functions — moderation queue ────────────────────────────────

async def list_flags(
    db: AsyncSession,
    status: str | None,
    reason: str | None,
    cursor: str | None,
    limit: int,
) -> FlagPageOut:
    """Return a paginated page of moderation flags for the admin queue.

    Args:
        db: Async database session.
        status: Filter by flag status (e.g. ``"open"``); ``None`` returns all.
        reason: Filter by flag reason code; ``None`` returns all.
        cursor: Opaque cursor from the previous page; ``None`` for the first page.
        limit: Maximum number of flags per page.

    Returns:
        A ``FlagPageOut`` with the flag list and ``next_cursor`` (or ``None``).
    """
    stmt = (
        select(DiscussionFlag)
        .options(selectinload(DiscussionFlag.reporter))
        .order_by(DiscussionFlag.created_at.desc(), DiscussionFlag.id.desc())
    )

    if status is not None:
        stmt = stmt.where(DiscussionFlag.status == status)
    if reason is not None:
        stmt = stmt.where(DiscussionFlag.reason == reason)

    if cursor is not None:
        cur_ts, cur_id = decode_cursor(cursor)
        stmt = stmt.where(
            sa.or_(
                DiscussionFlag.created_at < cur_ts,
                sa.and_(
                    DiscussionFlag.created_at == cur_ts,
                    DiscussionFlag.id < cur_id,
                ),
            )
        )

    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    flags = list(result.scalars().all())

    has_more = len(flags) > limit
    page_flags = flags[:limit]

    next_cursor: str | None = None
    if has_more and page_flags:
        last = page_flags[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return FlagPageOut(
        flags=[_build_flag_out(f) for f in page_flags],
        next_cursor=next_cursor,
    )


async def resolve_flag(
    db: AsyncSession,
    admin_user: User,
    flag_id: uuid.UUID,
    outcome: str,
    resolution_note: str | None,
) -> DiscussionFlagOut:
    """Resolve a moderation flag with the given outcome.

    If *outcome* is ``"content_removed"``, the flagged post is also
    soft-deleted (if not already deleted).

    Args:
        db: Async database session.
        admin_user: Authenticated admin performing the resolution.
        flag_id: UUID of the flag to resolve.
        outcome: Resolution code: ``"dismissed"``, ``"content_removed"``,
            or ``"warned"``.
        resolution_note: Optional admin note to record with the resolution.

    Returns:
        The resolved ``DiscussionFlagOut`` DTO.

    Raises:
        DiscussionFlagNotFound: If no flag with that ID exists.
        DiscussionFlagAlreadyResolved: If the flag is not in ``"open"`` status.
    """
    flag = await db.get(DiscussionFlag, flag_id)
    if flag is None:
        raise DiscussionFlagNotFound()

    if flag.status != "open":
        raise DiscussionFlagAlreadyResolved()

    flag.status = outcome
    flag.resolved_by = admin_user.id
    flag.resolved_at = datetime.now(UTC)
    flag.resolution_note = resolution_note

    if outcome == "content_removed":
        post = await db.get(DiscussionPost, flag.post_id)
        if post is not None and post.deleted_at is None:
            post.body = TOMBSTONE
            post.deleted_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(flag, ["reporter"])
    return _build_flag_out(flag)
