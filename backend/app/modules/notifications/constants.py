"""Shared enums and defaults for notification types and delivery channels."""

from enum import StrEnum


class NotificationType(StrEnum):
    DISCUSSION_REPLY = "discussion_reply"
    MENTION = "mention"
    GRADE_PUBLISHED = "grade_published"
    CERTIFICATE_ISSUED = "certificate_issued"


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
)

DEFAULT_IN_APP_ENABLED = True
DEFAULT_EMAIL_ENABLED = True
