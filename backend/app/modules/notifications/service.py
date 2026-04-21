"""Business logic for persisted notifications and notification preferences."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import func, select, update

from app.db.models.notification import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from app.modules.notifications.constants import (
    ALL_NOTIFICATION_TYPES,
    DEFAULT_EMAIL_ENABLED,
    DEFAULT_IN_APP_ENABLED,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationType,
)
from app.modules.notifications.schemas import (
    ChannelPreferenceOut,
    ChannelPreferencePatch,
    NotificationOut,
    NotificationPrefsOut,
    NotificationPrefsPatchIn,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.user import User

_BODY_PREVIEW_LIMIT = 160
_DELIVERY_ERROR_LIMIT = 1000
_SYSTEM_ACTOR = "XOXO Education"


def encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    """Encode a notification cursor as a URL-safe string."""
    payload = f"{created_at.isoformat()}|{notification_id}"
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode an opaque notification cursor."""
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = payload.split("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except Exception as exc:
        raise ValueError(f"Invalid cursor: {cursor!r}") from exc


def _preview_body(body: str) -> str:
    """Trim notification copy to a readable preview."""
    compact = " ".join(body.split())
    if len(compact) <= _BODY_PREVIEW_LIMIT:
        return compact
    return f"{compact[:_BODY_PREVIEW_LIMIT - 1].rstrip()}…"


def _actor_summary(actor: User | None) -> str:
    """Return the display string stored with the notification event."""
    if actor is None:
        return _SYSTEM_ACTOR
    return actor.display_name or actor.username or actor.email.split("@", 1)[0]


def _prefs_row_to_out(row: NotificationPreference | None) -> ChannelPreferenceOut:
    """Materialize one preference row, falling back to default channel values."""
    if row is None:
        return ChannelPreferenceOut(
            in_app=DEFAULT_IN_APP_ENABLED,
            email=DEFAULT_EMAIL_ENABLED,
        )
    return ChannelPreferenceOut(
        in_app=row.in_app_enabled,
        email=row.email_enabled,
    )


def _truncate_error(exc: Exception) -> str:
    """Return a bounded error string safe to store in delivery rows."""
    return f"{type(exc).__name__}: {exc}"[:_DELIVERY_ERROR_LIMIT]


async def email_delivery_enabled(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    notification_type: str,
) -> bool:
    """Return whether a user's email preference allows this notification type."""
    pref = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type == notification_type,
        )
    )
    return pref.email_enabled if pref is not None else DEFAULT_EMAIL_ENABLED


async def _get_or_create_delivery(
    db: AsyncSession,
    *,
    notification_id: uuid.UUID,
    channel: NotificationChannel,
) -> NotificationDelivery:
    """Return the durable delivery row for one notification/channel."""
    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notification_id,
            NotificationDelivery.channel == channel.value,
        )
    )
    if delivery is None:
        delivery = NotificationDelivery(
            notification_id=notification_id,
            channel=channel.value,
            status=NotificationDeliveryStatus.QUEUED.value,
        )
        db.add(delivery)
        await db.flush()
    return delivery


async def dispatch_notification_delivery(
    db: AsyncSession,
    *,
    notification_id: uuid.UUID,
    recipient_id: uuid.UUID,
    notification_type: str,
    notification_out: NotificationOut,
    redis: aioredis.Redis | None = None,
) -> None:
    """Best-effort email enqueue and realtime publish for a committed notification.

    The notification row is the correctness layer. Delivery side effects are
    intentionally non-fatal: broker/Redis failures are recorded or logged without
    changing the response for the request that created the notification.
    """
    try:
        delivery = await _get_or_create_delivery(
            db,
            notification_id=notification_id,
            channel=NotificationChannel.EMAIL,
        )
        if await email_delivery_enabled(
            db,
            user_id=recipient_id,
            notification_type=notification_type,
        ):
            if delivery.status != NotificationDeliveryStatus.SENT.value:
                delivery.status = NotificationDeliveryStatus.QUEUED.value
                delivery.queued_at = delivery.queued_at or datetime.now(UTC)
                delivery.failed_at = None
                delivery.last_error = None
                await db.commit()

                from app.modules.notifications.tasks import send_notification_email

                try:
                    send_notification_email.delay(str(notification_id))
                except Exception as exc:
                    delivery.status = NotificationDeliveryStatus.FAILED.value
                    delivery.failed_at = datetime.now(UTC)
                    delivery.last_error = _truncate_error(exc)
                    await db.commit()
                    logger.exception(
                        "Failed to enqueue notification email",
                        extra={"notification_id": str(notification_id)},
                    )
        else:
            delivery.status = NotificationDeliveryStatus.SKIPPED.value
            delivery.failed_at = None
            delivery.last_error = "email preference disabled"
            await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to record notification email delivery state",
            extra={"notification_id": str(notification_id)},
        )

    try:
        if redis is None:
            from app.core.redis import get_redis

            redis = get_redis()
        await publish_notification(redis, recipient_id, notification_out)
    except Exception:
        logger.exception(
            "Failed to publish realtime notification",
            extra={"notification_id": str(notification_id)},
        )


def merge_channel_preferences(
    current: ChannelPreferenceOut,
    patch: ChannelPreferencePatch,
) -> ChannelPreferenceOut:
    """Merge a partial preference update without resetting omitted fields."""
    return ChannelPreferenceOut(
        in_app=current.in_app if patch.in_app is None else patch.in_app,
        email=current.email if patch.email is None else patch.email,
    )


def build_discussion_reply_notification(
    *,
    recipient_id: uuid.UUID,
    actor: User,
    lesson_id: uuid.UUID,
    parent_post_id: uuid.UUID,
    reply_post_id: uuid.UUID,
    reply_body: str,
) -> Notification:
    """Construct a persisted notification for a new discussion reply."""
    actor_text = _actor_summary(actor)
    return Notification(
        recipient_id=recipient_id,
        type=NotificationType.DISCUSSION_REPLY.value,
        title=f"{actor_text} replied to your discussion post",
        body=_preview_body(reply_body),
        actor_summary=actor_text,
        target_url=f"/lessons/{lesson_id}/discussions?post_id={parent_post_id}",
        event_metadata={
            "lesson_id": str(lesson_id),
            "post_id": str(reply_post_id),
            "parent_post_id": str(parent_post_id),
        },
    )


def build_mention_notification(
    *,
    recipient_id: uuid.UUID,
    actor: User,
    lesson_id: uuid.UUID,
    post_id: uuid.UUID,
    post_body: str,
    mentioned_username: str,
) -> Notification:
    """Construct a persisted notification for a discussion mention."""
    actor_text = _actor_summary(actor)
    return Notification(
        recipient_id=recipient_id,
        type=NotificationType.MENTION.value,
        title=f"{actor_text} mentioned you in a discussion",
        body=_preview_body(post_body),
        actor_summary=actor_text,
        target_url=f"/lessons/{lesson_id}/discussions?post_id={post_id}",
        event_metadata={
            "lesson_id": str(lesson_id),
            "post_id": str(post_id),
            "mentioned_username": mentioned_username,
        },
    )


def build_grade_published_notification(
    *,
    recipient_id: uuid.UUID,
    actor: User | None,
    assignment_id: uuid.UUID,
    submission_id: uuid.UUID,
    grade_score: float | None,
) -> Notification:
    """Construct a persisted notification for a published assignment grade."""
    actor_text = _actor_summary(actor)
    score_text = (
        f"Your grade is now available. Score: {grade_score:.1f}."
        if grade_score is not None
        else "Your grade is now available."
    )
    return Notification(
        recipient_id=recipient_id,
        type=NotificationType.GRADE_PUBLISHED.value,
        title="Your assignment grade was published",
        body=score_text,
        actor_summary=actor_text,
        target_url=f"/assignments/{assignment_id}/submissions/{submission_id}",
        event_metadata={
            "assignment_id": str(assignment_id),
            "submission_id": str(submission_id),
            "grade_score": grade_score,
        },
    )


def build_certificate_issued_notification(
    *,
    recipient_id: uuid.UUID,
    certificate_id: uuid.UUID,
    course_id: uuid.UUID,
) -> Notification:
    """Construct a persisted notification for a newly issued certificate."""
    return Notification(
        recipient_id=recipient_id,
        type=NotificationType.CERTIFICATE_ISSUED.value,
        title="Your certificate is ready",
        body="Your course-completion certificate has been issued.",
        actor_summary=_SYSTEM_ACTOR,
        target_url=f"/certificates/{certificate_id}",
        event_metadata={
            "certificate_id": str(certificate_id),
            "course_id": str(course_id),
        },
    )


def notification_to_out(notification: Notification) -> NotificationOut:
    """Convert an ORM notification row to the public API schema."""
    return NotificationOut(
        id=notification.id,
        type=NotificationType(notification.type),
        title=notification.title,
        body=notification.body,
        actor_summary=notification.actor_summary,
        target_url=notification.target_url,
        event_metadata=notification.event_metadata,
        is_read=notification.read_at is not None,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


def stage_notification(
    db: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str,
    actor_summary: str,
    target_url: str,
    event_metadata: dict[str, Any],
) -> Notification:
    """Add a generic notification row to the current transaction."""
    notification = Notification(
        recipient_id=recipient_id,
        type=type.value,
        title=title,
        body=body,
        actor_summary=actor_summary,
        target_url=target_url,
        event_metadata=event_metadata,
    )
    db.add(notification)
    return notification


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    cursor: str | None,
    limit: int,
) -> tuple[list[NotificationOut], str | None, int]:
    """Return one page of notifications plus the unread count."""
    stmt = (
        select(Notification)
        .where(Notification.recipient_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    )
    if cursor is not None:
        cur_ts, cur_id = decode_cursor(cursor)
        stmt = stmt.where(
            sa.or_(
                Notification.created_at < cur_ts,
                sa.and_(Notification.created_at == cur_ts, Notification.id < cur_id),
            )
        )

    rows = list((await db.scalars(stmt.limit(limit + 1))).all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    unread_count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_id == user_id,
            Notification.read_at.is_(None),
        )
    ) or 0

    return [notification_to_out(row) for row in page_rows], next_cursor, unread_count


async def mark_all_read(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Mark every unread notification for a user as read."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount or 0


async def get_preferences(db: AsyncSession, *, user_id: uuid.UUID) -> NotificationPrefsOut:
    """Return the current user's materialized preference snapshot."""
    rows = (
        await db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
    ).all()
    by_type = {row.notification_type: row for row in rows}
    return NotificationPrefsOut(
        discussion_reply=_prefs_row_to_out(by_type.get(NotificationType.DISCUSSION_REPLY.value)),
        mention=_prefs_row_to_out(by_type.get(NotificationType.MENTION.value)),
        grade_published=_prefs_row_to_out(by_type.get(NotificationType.GRADE_PUBLISHED.value)),
        certificate_issued=_prefs_row_to_out(
            by_type.get(NotificationType.CERTIFICATE_ISSUED.value)
        ),
    )


async def update_preferences(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    patch: NotificationPrefsPatchIn,
) -> NotificationPrefsOut:
    """Apply a partial, idempotent preference update for the current user."""
    rows = (
        await db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
    ).all()
    by_type = {row.notification_type: row for row in rows}

    for notification_type in ALL_NOTIFICATION_TYPES:
        update_patch = getattr(patch, notification_type.value)
        if update_patch is None:
            continue

        row = by_type.get(notification_type.value)
        current = _prefs_row_to_out(row)
        merged = merge_channel_preferences(current, update_patch)

        if row is None:
            row = NotificationPreference(
                user_id=user_id,
                notification_type=notification_type.value,
            )
            db.add(row)
            by_type[notification_type.value] = row

        row.in_app_enabled = merged.in_app
        row.email_enabled = merged.email

    await db.commit()
    return await get_preferences(db, user_id=user_id)


async def publish_notification(
    redis: aioredis.Redis,
    user_id: uuid.UUID,
    notification_out: NotificationOut,
) -> None:
    """Publish a notification payload to the user's realtime SSE channel.

    The channel ``notifications:user:{user_id}`` is the signal used by any
    connected ``GET /api/v1/notifications/stream`` listener to wake up and
    emit the event.  Call this *after* committing the notification row so the
    DB record exists before the consumer can act on it.

    Args:
        redis: Async Redis client.
        user_id: UUID of the notification's recipient.
        notification_out: Fully serialized notification DTO to broadcast.
    """
    channel = f"notifications:user:{user_id}"
    await redis.publish(channel, notification_out.model_dump_json())
