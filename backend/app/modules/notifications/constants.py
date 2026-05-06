"""Shared enums and defaults for notification types and delivery channels."""

from enum import StrEnum


class NotificationType(StrEnum):
    DISCUSSION_REPLY = "discussion_reply"
    MENTION = "mention"
    GRADE_PUBLISHED = "grade_published"
    CERTIFICATE_ISSUED = "certificate_issued"
    LIVE_SESSION_REMINDER = "live_session_reminder"
    PAYMENT_DUE_SOON = "payment_due_soon"
    PAYMENT_PROCESSED = "payment_processed"
    PAYMENT_FAILED = "payment_failed"


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"


class NotificationDeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


ALL_NOTIFICATION_TYPES: tuple[NotificationType, ...] = (
    NotificationType.DISCUSSION_REPLY,
    NotificationType.MENTION,
    NotificationType.GRADE_PUBLISHED,
    NotificationType.CERTIFICATE_ISSUED,
    NotificationType.LIVE_SESSION_REMINDER,
    NotificationType.PAYMENT_DUE_SOON,
    NotificationType.PAYMENT_PROCESSED,
    NotificationType.PAYMENT_FAILED,
)

DEFAULT_IN_APP_ENABLED = True
DEFAULT_EMAIL_ENABLED = True
