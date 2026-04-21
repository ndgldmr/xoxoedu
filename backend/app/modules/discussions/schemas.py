"""Pydantic schemas for discussion post requests and responses."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Shared sub-objects ─────────────────────────────────────────────────────────

class AuthorOut(BaseModel):
    """Minimal author summary included in every post response."""

    id: uuid.UUID
    username: str
    display_name: str | None
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


# ── Post schemas ───────────────────────────────────────────────────────────────

class CreatePostIn(BaseModel):
    """Request body for creating a top-level post or reply."""

    body: str = Field(..., min_length=1, max_length=10_000)
    parent_id: uuid.UUID | None = None


class EditPostIn(BaseModel):
    """Request body for editing a discussion post."""

    body: str = Field(..., min_length=1, max_length=10_000)


class DiscussionPostOut(BaseModel):
    """Full representation of a discussion post returned to the client."""

    id: uuid.UUID
    lesson_id: uuid.UUID
    parent_id: uuid.UUID | None
    body: str
    is_deleted: bool
    edited_at: datetime | None
    created_at: datetime
    author: AuthorOut
    reply_count: int
    upvote_count: int = 0
    viewer_has_upvoted: bool = False
    mentions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ThreadPageOut(BaseModel):
    """Paginated discussion thread response with opaque cursor."""

    posts: list[DiscussionPostOut]
    next_cursor: str | None


# ── Flag schemas ───────────────────────────────────────────────────────────────

FlagReason = Literal["spam", "harassment", "misinformation", "off_topic", "other"]
FlagOutcome = Literal["dismissed", "content_removed", "warned"]


class FlagIn(BaseModel):
    """Request body for flagging a discussion post."""

    reason: FlagReason
    context: str | None = Field(None, max_length=500)


class ResolveFlagIn(BaseModel):
    """Request body for resolving a moderation flag."""

    outcome: FlagOutcome
    resolution_note: str | None = Field(None, max_length=500)


class DiscussionFlagOut(BaseModel):
    """Full representation of a moderation flag."""

    id: uuid.UUID
    post_id: uuid.UUID
    reason: str
    context: str | None
    status: str
    reporter: AuthorOut
    resolved_by_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FlagPageOut(BaseModel):
    """Paginated moderation flag queue response with opaque cursor."""

    flags: list[DiscussionFlagOut]
    next_cursor: str | None
