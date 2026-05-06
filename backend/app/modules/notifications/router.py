"""FastAPI router for notification feed, preference, and realtime stream endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002
from sse_starlette.sse import EventSourceResponse

from app.core.redis import get_redis
from app.core.responses import ok
from app.db.models.user import User  # noqa: TC001
from app.db.session import get_db
from app.dependencies import get_current_verified_user
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationPrefsPatchIn  # noqa: TC001

router = APIRouter(tags=["notifications"])


async def notification_stream_events(
    redis,
    user_id: uuid.UUID,
    *,
    poll_interval: float = 0.5,
    heartbeat_interval: float = 15,
) -> AsyncGenerator[dict, None]:
    """Yield SSE events from the authenticated user's Redis notification channel."""
    import asyncio

    channel = f"notifications:user:{user_id}"
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    last_heartbeat = asyncio.get_running_loop().time()
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=poll_interval,
            )
            if message is not None and message["type"] == "message":
                yield {"event": "notification", "data": message["data"]}
                last_heartbeat = asyncio.get_running_loop().time()
            elif asyncio.get_running_loop().time() - last_heartbeat >= heartbeat_interval:
                yield {"data": ""}
                last_heartbeat = asyncio.get_running_loop().time()
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()


@router.get("/users/me/notifications")
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_verified_user),
    cursor: str | None = Query(None, description="Opaque cursor from a previous page"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Return the current user's notification feed and unread count metadata."""
    notifications, next_cursor, unread_count = await service.list_notifications(
        db,
        user_id=current_user.id,
        cursor=cursor,
        limit=limit,
    )
    return ok(
        [notification.model_dump() for notification in notifications],
        meta={"next_cursor": next_cursor, "unread_count": unread_count},
    )


@router.post("/users/me/notifications/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_verified_user),
) -> dict:
    """Mark every unread notification for the current user as read."""
    marked_read = await service.mark_all_read(db, user_id=current_user.id)
    return ok({"marked_read": marked_read})


@router.patch("/users/me/notification-prefs")
async def update_notification_preferences(
    body: NotificationPrefsPatchIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_verified_user),
) -> dict:
    """Partially update notification-channel preferences for the current user."""
    prefs = await service.update_preferences(
        db,
        user_id=current_user.id,
        patch=body,
    )
    return ok(prefs.model_dump())


@router.get("/users/me/notifications/stream")
async def stream_notifications(
    current_user: User = Depends(get_current_verified_user),
) -> EventSourceResponse:
    """Subscribe to realtime notification delivery via Server-Sent Events.

    Maintains a long-lived connection and emits one SSE event per new
    notification as it is published to the user's Redis channel.  Heartbeat
    pings (empty ``data`` lines) are sent every 15 seconds so intermediary
    proxies do not close idle connections.

    Event protocol:
    - ``event: notification`` with ``data: <NotificationOut JSON>`` — new notification

    Clients should reconnect automatically (the browser ``EventSource`` API
    does this by default) and combine the stream with
    ``GET /api/v1/users/me/notifications`` to recover any missed items.

    Args:
        current_user: Authenticated, verified user.

    Returns:
        ``EventSourceResponse`` wrapping the async notification generator.
    """
    return EventSourceResponse(notification_stream_events(get_redis(), current_user.id))
