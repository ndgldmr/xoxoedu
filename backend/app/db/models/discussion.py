"""ORM models for lesson discussion posts, votes, and moderation flags."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class DiscussionPost(Base, UUIDMixin):
    """A student or admin post in a lesson's discussion thread.

    Posts are either top-level (``parent_id`` is ``None``) or replies to a
    top-level post.  Deletes are always soft: ``deleted_at`` is stamped and
    the ``body`` is replaced with a tombstone so reply context is preserved.

    Attributes:
        lesson_id: The lesson this post belongs to.
        author_id: The user who created the post.
        parent_id: The top-level post this is a reply to; ``None`` for top-level posts.
        body: Post text content (replaced with tombstone text on soft-delete).
        deleted_at: Timestamp of soft-delete; ``None`` while the post is live.
        edited_at: Timestamp of the most recent edit; ``None`` if never edited.
        created_at: Row creation timestamp (server-side).
        updated_at: Row last-update timestamp (Python-side ``onupdate``).
        author: The ``User`` who authored the post (eager-loadable).
    """

    __tablename__ = "discussion_posts"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discussion_posts.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    author: Mapped[Optional[User]] = relationship("User", foreign_keys=[author_id])

    __table_args__ = (
        # Hot-path index: fetch all posts for a lesson, filtered by parent
        Index("ix_discussion_posts_lesson_parent_created", "lesson_id", "parent_id", "created_at"),
        # Stand-alone indexes for individual filter predicates
        Index("ix_discussion_posts_lesson_id", "lesson_id"),
        Index("ix_discussion_posts_parent_id", "parent_id"),
        Index("ix_discussion_posts_created_at", "created_at"),
    )


class DiscussionPostVote(Base, UUIDMixin):
    """One upvote cast by a user on a discussion post.

    The unique constraint ``uq_discussion_post_votes_post_user`` enforces that
    each user may upvote a given post at most once.  Toggling is implemented
    by deleting the row rather than using a boolean column, keeping the schema
    append-only and making audit queries straightforward.

    Attributes:
        post_id: The discussion post being upvoted.
        user_id: The user casting the upvote.
        created_at: Timestamp of the upvote.
    """

    __tablename__ = "discussion_post_votes"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discussion_posts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_discussion_post_votes_post_user"),
        Index("ix_discussion_post_votes_post_id", "post_id"),
        Index("ix_discussion_post_votes_user_id", "user_id"),
    )


class DiscussionFlag(Base, UUIDMixin):
    """A moderation flag raised against a discussion post.

    At most one *open* flag may exist per ``(post_id, reporter_id)`` pair,
    enforced by the partial unique index
    ``uq_discussion_flags_open_per_user_post`` (``WHERE status = 'open'``).
    Resolved flags are kept as an immutable audit trail.

    Attributes:
        post_id: The post being flagged.
        reporter_id: The user who raised the flag.
        reason: Categorisation code (``spam``, ``harassment``,
            ``misinformation``, ``off_topic``, ``other``).
        context: Optional free-text note from the reporter.
        status: Lifecycle state: ``open`` → ``dismissed`` / ``content_removed``
            / ``warned``.
        resolved_by: Admin who resolved the flag; ``None`` while open.
        resolved_at: Resolution timestamp; ``None`` while open.
        resolution_note: Optional admin note recorded at resolution.
        created_at: Flag creation timestamp.
        updated_at: Last-modified timestamp.
        reporter: The ``User`` who reported the post.
        resolver: The admin ``User`` who resolved the flag (or ``None``).
        post: The flagged ``DiscussionPost``.
    """

    __tablename__ = "discussion_flags"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discussion_posts.id", ondelete="CASCADE"), nullable=False
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    reporter: Mapped[Optional[User]] = relationship("User", foreign_keys=[reporter_id])
    resolver: Mapped[Optional[User]] = relationship("User", foreign_keys=[resolved_by])
    post: Mapped[Optional[DiscussionPost]] = relationship("DiscussionPost", foreign_keys=[post_id])

    __table_args__ = (
        # Moderation queue hot-path indexes
        Index("ix_discussion_flags_status", "status"),
        Index("ix_discussion_flags_created_at", "created_at"),
        Index("ix_discussion_flags_post_id", "post_id"),
    )
