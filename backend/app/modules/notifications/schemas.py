"""Pydantic schemas for notification feed and preference endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.notifications.constants import NotificationType  # noqa: TC001


class NotificationOut(BaseModel):
    """One notification row returned in the authenticated user's feed."""

    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    actor_summary: str
    target_url: str
    event_metadata: dict[str, Any]
    is_read: bool
    read_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelPreferencePatch(BaseModel):
    """Partial update for one notification type's channel settings."""

    in_app: bool | None = None
    email: bool | None = None


class ChannelPreferenceOut(BaseModel):
    """Fully materialized channel preferences for one notification type."""

    in_app: bool
    email: bool


class NotificationPrefsPatchIn(BaseModel):
    """Partial preference update keyed by notification type."""

    discussion_reply: ChannelPreferencePatch | None = None
    mention: ChannelPreferencePatch | None = None
    grade_published: ChannelPreferencePatch | None = None
    certificate_issued: ChannelPreferencePatch | None = None
    live_session_reminder: ChannelPreferencePatch | None = None
    payment_due_soon: ChannelPreferencePatch | None = None
    payment_processed: ChannelPreferencePatch | None = None
    payment_failed: ChannelPreferencePatch | None = None


class NotificationPrefsOut(BaseModel):
    """Snapshot of all notification channel preferences for the user."""

    discussion_reply: ChannelPreferenceOut
    mention: ChannelPreferenceOut
    grade_published: ChannelPreferenceOut
    certificate_issued: ChannelPreferenceOut
    live_session_reminder: ChannelPreferenceOut
    payment_due_soon: ChannelPreferenceOut
    payment_processed: ChannelPreferenceOut
    payment_failed: ChannelPreferenceOut
