"""Unit tests for notification builders, preference helpers, and email tasks."""

import uuid
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.db.models.user import User
from app.modules.notifications.constants import NotificationType
from app.modules.notifications.schemas import (
    ChannelPreferenceOut,
    ChannelPreferencePatch,
    NotificationOut,
)
from app.modules.notifications.service import (
    billing_reminder_eligible,
    build_discussion_reply_notification,
    build_payment_due_soon_notification,
    merge_channel_preferences,
)
from app.modules.notifications.tasks import _render_notification_email


def _make_user(
    *,
    email: str = "author@example.com",
    username: str = "author_user",
    display_name: str | None = "Author User",
) -> User:
    user = User()
    user.id = uuid.uuid4()
    user.email = email
    user.username = username
    user.display_name = display_name
    user.role = "student"
    user.email_verified = True
    return user


def test_build_discussion_reply_notification() -> None:
    actor = _make_user(display_name="Alice")
    lesson_id = uuid.uuid4()
    parent_post_id = uuid.uuid4()
    reply_post_id = uuid.uuid4()
    notification = build_discussion_reply_notification(
        recipient_id=uuid.uuid4(),
        actor=actor,
        lesson_id=lesson_id,
        parent_post_id=parent_post_id,
        reply_post_id=reply_post_id,
        reply_body="Thanks for the detailed explanation on this lesson.",
    )

    assert notification.type == NotificationType.DISCUSSION_REPLY.value
    assert notification.title == "Alice replied to your discussion post"
    assert notification.body.startswith("Thanks for the detailed explanation")
    assert notification.target_url == f"/lessons/{lesson_id}/discussions?post_id={parent_post_id}"
    assert notification.event_metadata["post_id"] == str(reply_post_id)


def test_build_payment_due_soon_notification() -> None:
    notification = build_payment_due_soon_notification(
        recipient_id=uuid.uuid4(),
        subscription_id=uuid.uuid4(),
        billing_cycle_id=uuid.uuid4(),
        due_date=date(2026, 5, 1),
        amount_cents=1499,
        currency="eur",
        provider_invoice_id="in_test_123",
    )

    assert notification.type == NotificationType.PAYMENT_DUE_SOON.value
    assert notification.title == "Payment due in 3 days"
    assert "EUR 14.99" in notification.body
    assert notification.target_url == "/home/account"
    assert notification.event_metadata["provider_invoice_id"] == "in_test_123"
    assert notification.event_metadata["currency"] == "EUR"


def test_notification_out_rejects_invalid_enum_value() -> None:
    with pytest.raises(ValidationError):
        NotificationOut(
            id=uuid.uuid4(),
            type="not_a_real_type",
            title="Bad",
            body="Bad",
            actor_summary="System",
            target_url="/notifications/bad",
            event_metadata={},
            is_read=False,
            read_at=None,
            created_at=datetime(2026, 4, 20, tzinfo=UTC),
        )


def test_merge_channel_preferences_preserves_omitted_fields() -> None:
    current = ChannelPreferenceOut(in_app=True, email=False)
    merged = merge_channel_preferences(
        current,
        ChannelPreferencePatch(in_app=False),
    )

    assert merged.in_app is False
    assert merged.email is False


# ── Email template rendering ───────────────────────────────────────────────────


def test_render_discussion_reply_email_contains_actor_and_cta() -> None:
    subject, html = _render_notification_email(
        notification_type="discussion_reply",
        title="Alice replied to your discussion post",
        body="Thanks for the explanation!",
        target_url="/lessons/abc/discussions?post_id=xyz",
        actor_summary="Alice",
        frontend_url="https://app.xoxoedu.com",
    )

    assert "Alice" in subject
    assert "replied" in subject
    assert "Thanks for the explanation!" in html
    assert "https://app.xoxoedu.com/lessons/abc/discussions?post_id=xyz" in html
    assert "View Reply" in html


def test_render_notification_email_escapes_user_controlled_content() -> None:
    subject, html = _render_notification_email(
        notification_type="discussion_reply",
        title="<script>alert('title')</script>",
        body="<img src=x onerror=alert('body')>",
        target_url='/lessons/abc?next="bad"',
        actor_summary="Alice",
        frontend_url="https://app.xoxoedu.com/",
    )

    assert subject == "Alice replied to your discussion post"
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(&#x27;title&#x27;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(&#x27;body&#x27;)&gt;" in html
    assert 'href="https://app.xoxoedu.com/lessons/abc?next=&quot;bad&quot;"' in html


def test_render_mention_email_contains_actor_and_cta() -> None:
    subject, html = _render_notification_email(
        notification_type="mention",
        title="Bob mentioned you in a discussion",
        body="Hey @carol, check this out.",
        target_url="/lessons/def/discussions?post_id=uvw",
        actor_summary="Bob",
        frontend_url="https://app.xoxoedu.com",
    )

    assert "Bob" in subject
    assert "mentioned" in subject
    assert "View Post" in html


def test_render_grade_published_email_contains_cta() -> None:
    subject, html = _render_notification_email(
        notification_type="grade_published",
        title="Your assignment grade was published",
        body="Your grade is now available. Score: 87.0.",
        target_url="/assignments/123/submissions/456",
        actor_summary="Instructor",
        frontend_url="https://app.xoxoedu.com",
    )

    assert "grade" in subject.lower()
    assert "Score: 87.0" in html
    assert "View Grade" in html


def test_render_certificate_issued_email_contains_cta() -> None:
    subject, html = _render_notification_email(
        notification_type="certificate_issued",
        title="Your certificate is ready",
        body="Your course-completion certificate has been issued.",
        target_url="/certificates/789",
        actor_summary="XOXO Education",
        frontend_url="https://app.xoxoedu.com",
    )

    assert "certificate" in subject.lower()
    assert "View Certificate" in html
    assert "https://app.xoxoedu.com/certificates/789" in html


def test_render_payment_due_soon_email_contains_billing_cta() -> None:
    subject, html = _render_notification_email(
        notification_type="payment_due_soon",
        title="Payment due in 3 days",
        body="Your subscription payment of BRL 10.00 is due on 2026-05-01.",
        target_url="/home/account",
        actor_summary="XOXO Education",
        frontend_url="https://app.xoxoedu.com",
    )

    assert "Payment due in 3 days" in subject
    assert "BRL 10.00" in html
    assert "View Billing" in html
    assert 'href="https://app.xoxoedu.com/home/account"' in html


def test_render_payment_failed_email_contains_billing_cta() -> None:
    subject, html = _render_notification_email(
        notification_type="payment_failed",
        title="Payment failed",
        body="We could not process your subscription payment of CAD 10.00.",
        target_url="/home/account",
        actor_summary="XOXO Education",
        frontend_url="https://app.xoxoedu.com",
    )

    assert "Payment failed" in subject
    assert "CAD 10.00" in html
    assert "View Billing" in html


# ── Email preference gating ────────────────────────────────────────────────────


def test_render_unknown_notification_type_falls_back_to_title() -> None:
    """An unrecognised notification type should fall back to the title as subject."""
    subject, html = _render_notification_email(
        notification_type="unknown_future_type",
        title="Something happened",
        body="Details here.",
        target_url="/somewhere",
        actor_summary="System",
        frontend_url="https://app.xoxoedu.com",
    )

    assert subject == "Something happened"
    assert "Details here." in html
    assert "View" in html  # generic CTA label


def test_billing_reminder_eligible_only_for_pending_due_soon_cycle() -> None:
    assert billing_reminder_eligible(
        cycle_status="pending",
        due_date=date(2026, 5, 1),
        reminder_sent_at=None,
        subscription_status="active",
        today=date(2026, 4, 28),
    ) is True


@pytest.mark.parametrize(
    ("cycle_status", "due_date", "reminder_sent_at", "subscription_status"),
    [
        ("paid", date(2026, 5, 1), None, "active"),
        ("failed", date(2026, 5, 1), None, "active"),
        ("pending", date(2026, 5, 2), None, "active"),
        ("pending", date(2026, 5, 1), datetime(2026, 4, 28, tzinfo=UTC), "active"),
        ("pending", date(2026, 5, 1), None, "canceled"),
    ],
)
def test_billing_reminder_eligible_skip_rules(
    cycle_status: str,
    due_date: date,
    reminder_sent_at: datetime | None,
    subscription_status: str,
) -> None:
    assert billing_reminder_eligible(
        cycle_status=cycle_status,
        due_date=due_date,
        reminder_sent_at=reminder_sent_at,
        subscription_status=subscription_status,
        today=date(2026, 4, 28),
    ) is False
