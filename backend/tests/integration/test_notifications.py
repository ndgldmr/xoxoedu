"""Integration tests for notification feed, read state, prefs, producers, and delivery."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.discussion import DiscussionPost
from app.db.models.enrollment import Enrollment
from app.db.models.notification import Notification, NotificationDelivery, NotificationPreference
from app.db.models.user import User
from app.modules.notifications.constants import NotificationDeliveryStatus, NotificationType
from app.modules.notifications.service import notification_to_out


async def _make_user(
    db: AsyncSession,
    email: str,
    *,
    role: str = "student",
    username: str | None = None,
    display_name: str | None = None,
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=username or f"user_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("testpass123"),
        role=role,
        email_verified=True,
        display_name=display_name or email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course(db: AsyncSession, created_by: uuid.UUID) -> Course:
    course = Course(
        slug=f"notif-course-{uuid.uuid4().hex[:8]}",
        title="Notification Test Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_chapter(db: AsyncSession, course_id: uuid.UUID) -> Chapter:
    chapter = Chapter(course_id=course_id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def _make_lesson(db: AsyncSession, chapter_id: uuid.UUID) -> Lesson:
    lesson = Lesson(chapter_id=chapter_id, title="Lesson 1", type="text", position=1)
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_enrollment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> Enrollment:
    enrollment = Enrollment(user_id=user_id, course_id=course_id, status="active")
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def _make_post(
    db: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str,
    parent_id: uuid.UUID | None = None,
) -> DiscussionPost:
    post = DiscussionPost(
        lesson_id=lesson_id,
        author_id=author_id,
        body=body,
        parent_id=parent_id,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post


async def _make_notification(
    db: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    notification_id: uuid.UUID | None = None,
    type: str = NotificationType.MENTION.value,
    title: str = "Notification",
    body: str = "Body",
    actor_summary: str = "System",
    target_url: str = "/notifications/test",
    event_metadata: dict | None = None,
    created_at: datetime | None = None,
    read_at: datetime | None = None,
) -> Notification:
    notification = Notification(
        id=notification_id or uuid.uuid4(),
        recipient_id=recipient_id,
        type=type,
        title=title,
        body=body,
        actor_summary=actor_summary,
        target_url=target_url,
        event_metadata=event_metadata or {},
        created_at=created_at,
        read_at=read_at,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def _setup_lesson(db: AsyncSession) -> tuple[Course, Lesson, uuid.UUID]:
    admin, _ = await _make_user(
        db,
        f"notif-admin-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
        display_name="Notif Admin",
    )
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    return course, lesson, admin.id


@pytest.mark.asyncio
async def test_reply_creates_notification_for_parent_author(
    client: AsyncClient, db: AsyncSession
) -> None:
    course, lesson, _ = await _setup_lesson(db)
    author, author_token = await _make_user(
        db,
        f"notif-author-{uuid.uuid4().hex[:6]}@example.com",
        username="thread_author",
        display_name="Thread Author",
    )
    replier, replier_token = await _make_user(
        db,
        f"notif-replier-{uuid.uuid4().hex[:6]}@example.com",
        username="reply_author",
        display_name="Reply Author",
    )
    await _make_enrollment(db, user_id=author.id, course_id=course.id)
    await _make_enrollment(db, user_id=replier.id, course_id=course.id)
    parent = await _make_post(
        db,
        lesson_id=lesson.id,
        author_id=author.id,
        body="Original question",
    )

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Here is a reply", "parent_id": str(parent.id)},
        headers={"Authorization": f"Bearer {replier_token}"},
    )

    assert resp.status_code == 201

    feed_resp = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert feed_resp.status_code == 200
    body = feed_resp.json()
    assert body["meta"]["unread_count"] == 1
    assert body["data"][0]["type"] == NotificationType.DISCUSSION_REPLY.value
    assert body["data"][0]["actor_summary"] == "Reply Author"


@pytest.mark.asyncio
async def test_mention_creates_notification_for_target_user(
    client: AsyncClient, db: AsyncSession
) -> None:
    course, lesson, _ = await _setup_lesson(db)
    author, author_token = await _make_user(
        db,
        f"notif-mention-author-{uuid.uuid4().hex[:6]}@example.com",
        username="mention_author",
        display_name="Mention Author",
    )
    target, target_token = await _make_user(
        db,
        f"notif-target-{uuid.uuid4().hex[:6]}@example.com",
        username="target_user",
        display_name="Target User",
    )
    await _make_enrollment(db, user_id=author.id, course_id=course.id)
    await _make_enrollment(db, user_id=target.id, course_id=course.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Thanks @target_user for the assist"},
        headers={"Authorization": f"Bearer {author_token}"},
    )

    assert resp.status_code == 201

    feed_resp = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {target_token}"},
    )
    assert feed_resp.status_code == 200
    body = feed_resp.json()
    assert body["meta"]["unread_count"] == 1
    assert body["data"][0]["type"] == NotificationType.MENTION.value
    assert body["data"][0]["event_metadata"]["mentioned_username"] == "target_user"


@pytest.mark.asyncio
async def test_read_all_marks_only_current_users_notifications_as_read(
    client: AsyncClient, db: AsyncSession
) -> None:
    user, token = await _make_user(db, f"notif-read-{uuid.uuid4().hex[:6]}@example.com")
    other_user, _ = await _make_user(db, f"notif-other-{uuid.uuid4().hex[:6]}@example.com")
    first = await _make_notification(db, recipient_id=user.id, title="First")
    second = await _make_notification(db, recipient_id=user.id, title="Second")
    other = await _make_notification(db, recipient_id=other_user.id, title="Other")

    resp = await client.post(
        "/api/v1/notifications/read-all",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["marked_read"] == 2

    refreshed = (
        await db.scalars(
            select(Notification).where(Notification.id.in_([first.id, second.id, other.id]))
        )
    ).all()
    by_id = {row.id: row for row in refreshed}
    assert by_id[first.id].read_at is not None
    assert by_id[second.id].read_at is not None
    assert by_id[other.id].read_at is None


@pytest.mark.asyncio
async def test_notification_feed_returns_unread_count_and_deterministic_order(
    client: AsyncClient, db: AsyncSession
) -> None:
    user, token = await _make_user(db, f"notif-feed-{uuid.uuid4().hex[:6]}@example.com")
    ts = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    older_ts = datetime(2026, 4, 20, 11, 0, 0, tzinfo=UTC)
    low_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    await _make_notification(
        db,
        recipient_id=user.id,
        notification_id=low_id,
        title="Low",
        created_at=ts,
        read_at=ts,
    )
    await _make_notification(
        db,
        recipient_id=user.id,
        notification_id=high_id,
        title="High",
        created_at=ts,
    )
    older = await _make_notification(
        db,
        recipient_id=user.id,
        title="Older",
        created_at=older_ts,
    )

    resp = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    titles = [item["title"] for item in body["data"]]
    assert titles == ["High", "Low", "Older"]
    assert body["meta"]["unread_count"] == 2
    assert body["data"][2]["id"] == str(older.id)


@pytest.mark.asyncio
async def test_patch_notification_prefs_is_partial_and_idempotent(
    client: AsyncClient, db: AsyncSession
) -> None:
    user, token = await _make_user(db, f"notif-prefs-{uuid.uuid4().hex[:6]}@example.com")

    first_resp = await client.patch(
        "/api/v1/notification-prefs",
        json={"mention": {"email": False}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first_resp.status_code == 200
    first_data = first_resp.json()["data"]
    assert first_data["mention"] == {"in_app": True, "email": False}
    assert first_data["discussion_reply"] == {"in_app": True, "email": True}

    second_resp = await client.patch(
        "/api/v1/notification-prefs",
        json={"mention": {"in_app": False}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert second_resp.status_code == 200
    second_data = second_resp.json()["data"]
    assert second_data["mention"] == {"in_app": False, "email": False}

    rows = (
        await db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    ).all()
    assert len(rows) == 1


# ── Sprint 10D: Notification Delivery & Realtime ───────────────────────────────


async def _make_assignment_for_course(
    db: AsyncSession, course: Course
) -> Assignment:
    chapter = Chapter(course_id=course.id, title="Ch 10D", position=99)
    db.add(chapter)
    await db.flush()
    lesson = Lesson(chapter_id=chapter.id, title="L 10D", position=1, type="assignment")
    db.add(lesson)
    await db.flush()
    assignment = Assignment(
        lesson_id=lesson.id,
        title="10D Test Assignment",
        instructions="Submit a report.",
        allowed_extensions=["pdf"],
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def _make_submission(
    db: AsyncSession,
    *,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AssignmentSubmission:
    submission = AssignmentSubmission(
        assignment_id=assignment_id,
        user_id=user_id,
        file_key="assignments/x/test.pdf",
        file_name="test.pdf",
        file_size=1024,
        mime_type="application/pdf",
        scan_status="clean",
        submitted_at=datetime.now(UTC),
        attempt_number=1,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return submission


# ── SSE stream endpoint ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_requires_authentication(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.get("/api/v1/notifications/stream")
    # The auth dependency returns 400 TOKEN_INVALID when no bearer token is present
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.asyncio
async def test_stream_route_returns_sse_response(db: AsyncSession) -> None:
    user, _ = await _make_user(db, f"stream-ct-{uuid.uuid4().hex[:6]}@example.com")

    from app.modules.notifications.router import stream_notifications

    resp = await stream_notifications(current_user=user)

    assert resp.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_stream_emits_notification_only_for_owning_user(
    db: AsyncSession,
) -> None:
    """SSE generator subscribes to and emits only the authenticated user's channel."""
    owner, _ = await _make_user(db, f"stream-owner-{uuid.uuid4().hex[:6]}@example.com")
    other, _ = await _make_user(db, f"stream-other-{uuid.uuid4().hex[:6]}@example.com")

    # Create a persisted notification for `owner`
    notif = await _make_notification(db, recipient_id=owner.id, title="Owner's Notification")
    notif_out = notification_to_out(notif)

    class FakePubSub:
        def __init__(self, payload: str) -> None:
            self.payload: str | None = payload
            self.subscribed_channel: str | None = None
            self.unsubscribed_channel: str | None = None
            self.closed = False

        async def subscribe(self, channel: str) -> None:
            self.subscribed_channel = channel

        async def get_message(self, **_kwargs: object) -> dict | None:
            if self.payload is None:
                return None
            payload = self.payload
            self.payload = None
            return {"type": "message", "data": payload}

        async def unsubscribe(self, channel: str) -> None:
            self.unsubscribed_channel = channel

        async def aclose(self) -> None:
            self.closed = True

    class FakeRedis:
        def __init__(self, pubsub: FakePubSub) -> None:
            self._pubsub = pubsub

        def pubsub(self) -> FakePubSub:
            return self._pubsub

    from app.modules.notifications.router import notification_stream_events

    fake_pubsub = FakePubSub(notif_out.model_dump_json())
    stream = notification_stream_events(
        FakeRedis(fake_pubsub),
        owner.id,
        poll_interval=0,
        heartbeat_interval=999,
    )
    try:
        event = await anext(stream)
    finally:
        await stream.aclose()

    assert fake_pubsub.subscribed_channel == f"notifications:user:{owner.id}"
    assert fake_pubsub.subscribed_channel != f"notifications:user:{other.id}"
    assert fake_pubsub.unsubscribed_channel == f"notifications:user:{owner.id}"
    assert fake_pubsub.closed is True
    assert event["event"] == "notification"
    assert json.loads(event["data"])["id"] == str(notif.id)


@pytest.mark.asyncio
async def test_disconnected_client_recovers_via_notification_poll(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Notifications created while the client is offline are visible via polling."""
    user, token = await _make_user(db, f"stream-recover-{uuid.uuid4().hex[:6]}@example.com")

    # Simulate a notification arriving while the client is "disconnected"
    await _make_notification(db, recipient_id=user.id, title="Missed While Offline")

    # Client reconnects and recovers via the polling endpoint
    resp = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["unread_count"] == 1
    assert data["data"][0]["title"] == "Missed While Offline"


# ── Email delivery gating ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_email_task_enqueued_on_discussion_reply(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A discussion reply enqueues send_notification_email for the parent author."""
    course, lesson, _ = await _setup_lesson(db)
    author, author_token = await _make_user(
        db,
        f"delivery-author-{uuid.uuid4().hex[:6]}@example.com",
        username=f"delivery_author_{uuid.uuid4().hex[:6]}",
        display_name="Delivery Author",
    )
    replier, replier_token = await _make_user(
        db,
        f"delivery-replier-{uuid.uuid4().hex[:6]}@example.com",
        username=f"delivery_replier_{uuid.uuid4().hex[:6]}",
        display_name="Delivery Replier",
    )
    await _make_enrollment(db, user_id=author.id, course_id=course.id)
    await _make_enrollment(db, user_id=replier.id, course_id=course.id)
    parent = await _make_post(
        db, lesson_id=lesson.id, author_id=author.id, body="Original question"
    )

    with patch(
        "app.modules.notifications.tasks.send_notification_email.delay"
    ) as mock_delay:
        resp = await client.post(
            f"/api/v1/lessons/{lesson.id}/discussions",
            json={"body": "A reply", "parent_id": str(parent.id)},
            headers={"Authorization": f"Bearer {replier_token}"},
        )

    assert resp.status_code == 201
    mock_delay.assert_called_once()
    called_notification_id = mock_delay.call_args[0][0]
    # Verify the notification exists in the DB
    notif = await db.scalar(
        select(Notification).where(Notification.id == uuid.UUID(called_notification_id))
    )
    assert notif is not None
    assert notif.type == NotificationType.DISCUSSION_REPLY.value
    assert notif.recipient_id == author.id

    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.QUEUED.value


@pytest.mark.asyncio
async def test_email_not_enqueued_when_preference_disabled(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A user's email opt-out prevents enqueue for that notification type."""
    course, lesson, _ = await _setup_lesson(db)
    author, _ = await _make_user(
        db,
        f"pref-opt-out-{uuid.uuid4().hex[:6]}@example.com",
        username=f"pref_author_{uuid.uuid4().hex[:6]}",
    )
    replier, replier_token = await _make_user(
        db,
        f"pref-replier-{uuid.uuid4().hex[:6]}@example.com",
        username=f"pref_replier_{uuid.uuid4().hex[:6]}",
    )
    await _make_enrollment(db, user_id=author.id, course_id=course.id)
    await _make_enrollment(db, user_id=replier.id, course_id=course.id)
    parent = await _make_post(
        db,
        lesson_id=lesson.id,
        author_id=author.id,
        body="Original question",
    )

    pref = NotificationPreference(
        user_id=author.id,
        notification_type=NotificationType.DISCUSSION_REPLY.value,
        in_app_enabled=True,
        email_enabled=False,
    )
    db.add(pref)
    await db.commit()

    with patch(
        "app.modules.notifications.tasks.send_notification_email.delay"
    ) as mock_delay:
        resp = await client.post(
            f"/api/v1/lessons/{lesson.id}/discussions",
            json={"body": "A reply", "parent_id": str(parent.id)},
            headers={"Authorization": f"Bearer {replier_token}"},
        )

    assert resp.status_code == 201
    mock_delay.assert_not_called()

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == author.id,
            Notification.type == NotificationType.DISCUSSION_REPLY.value,
        )
    )
    assert notif is not None

    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.SKIPPED.value


@pytest.mark.asyncio
async def test_email_enqueue_failure_does_not_fail_originating_request(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Broker enqueue failure is recorded but does not roll back the user action."""
    course, lesson, _ = await _setup_lesson(db)
    author, _ = await _make_user(
        db,
        f"enqueue-fail-author-{uuid.uuid4().hex[:6]}@example.com",
        username=f"enqueue_fail_author_{uuid.uuid4().hex[:6]}",
    )
    replier, replier_token = await _make_user(
        db,
        f"enqueue-fail-replier-{uuid.uuid4().hex[:6]}@example.com",
        username=f"enqueue_fail_replier_{uuid.uuid4().hex[:6]}",
    )
    await _make_enrollment(db, user_id=author.id, course_id=course.id)
    await _make_enrollment(db, user_id=replier.id, course_id=course.id)
    parent = await _make_post(
        db,
        lesson_id=lesson.id,
        author_id=author.id,
        body="Original question",
    )

    with patch(
        "app.modules.notifications.tasks.send_notification_email.delay",
        side_effect=RuntimeError("broker down"),
    ):
        resp = await client.post(
            f"/api/v1/lessons/{lesson.id}/discussions",
            json={"body": "A reply", "parent_id": str(parent.id)},
            headers={"Authorization": f"Bearer {replier_token}"},
        )

    assert resp.status_code == 201

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == author.id,
            Notification.type == NotificationType.DISCUSSION_REPLY.value,
        )
    )
    assert notif is not None

    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.FAILED.value
    assert "broker down" in delivery.last_error


# ── Grade published delivery ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grade_published_creates_notification_and_enqueues_delivery(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, admin_token = await _make_user(
        db,
        f"grade-admin-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
        username=f"grade_admin_{uuid.uuid4().hex[:6]}",
    )
    student, _ = await _make_user(
        db,
        f"grade-student-{uuid.uuid4().hex[:6]}@example.com",
        username=f"grade_student_{uuid.uuid4().hex[:6]}",
    )
    course = await _make_course(db, admin.id)
    await _make_enrollment(db, user_id=student.id, course_id=course.id)
    assignment = await _make_assignment_for_course(db, course)
    submission = await _make_submission(db, assignment_id=assignment.id, user_id=student.id)

    with patch(
        "app.modules.notifications.tasks.send_notification_email.delay"
    ) as mock_delay:
        resp = await client.patch(
            f"/api/v1/admin/submissions/{submission.id}/grade",
            json={"grade_score": 92.0, "grade_feedback": "Excellent", "publish": True},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 200
    mock_delay.assert_called_once()

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == student.id,
            Notification.type == NotificationType.GRADE_PUBLISHED.value,
        )
    )
    assert notif is not None
    assert notif.event_metadata["submission_id"] == str(submission.id)
    assert notif.event_metadata["grade_score"] == 92.0


# ── Certificate issued delivery ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_certificate_issued_creates_notification_and_enqueues_delivery(
    client: AsyncClient, db: AsyncSession
) -> None:
    from app.db.models.certificate import Certificate

    admin, _ = await _make_user(
        db,
        f"cert-notif-admin-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
    )
    student, student_token = await _make_user(
        db,
        f"cert-notif-student-{uuid.uuid4().hex[:6]}@example.com",
    )
    course = await _make_course(db, admin.id)
    enrollment = Enrollment(
        user_id=student.id, course_id=course.id, status="completed"
    )
    db.add(enrollment)
    await db.commit()

    with (
        patch("app.modules.certificates.tasks.generate_certificate_pdf.delay"),
        patch(
            "app.modules.notifications.tasks.send_notification_email.delay"
        ) as mock_delay,
    ):
        resp = await client.post(
            f"/api/v1/certificates/generate?course_id={course.id}",
            headers={"Authorization": f"Bearer {student_token}"},
        )

    assert resp.status_code == 201
    mock_delay.assert_called_once()

    cert = await db.scalar(
        select(Certificate).where(
            Certificate.user_id == student.id,
            Certificate.course_id == course.id,
        )
    )
    assert cert is not None

    notif = await db.scalar(
        select(Notification).where(
            Notification.recipient_id == student.id,
            Notification.type == NotificationType.CERTIFICATE_ISSUED.value,
        )
    )
    assert notif is not None
    assert notif.event_metadata["certificate_id"] == str(cert.id)


# ── Delivery task dedup guard ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delivery_task_dedup_guard_prevents_duplicate_send(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Running send_notification_email twice with the same ID only sends once."""
    user, _ = await _make_user(db, f"dedup-{uuid.uuid4().hex[:6]}@example.com")
    notif = await _make_notification(
        db,
        recipient_id=user.id,
        type=NotificationType.MENTION.value,
    )

    send_count = 0

    def counting_send(**kwargs: object) -> None:
        nonlocal send_count
        send_count += 1

    with patch("app.worker.email.send_email", side_effect=counting_send):
        from app.modules.notifications.tasks import send_notification_email
        send_notification_email.apply(args=[str(notif.id)])
        send_notification_email.apply(args=[str(notif.id)])  # blocked by guard key

    assert send_count == 1
    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notif.id,
            NotificationDelivery.channel == "email",
        )
    )
    assert delivery is not None
    assert delivery.status == NotificationDeliveryStatus.SENT.value
    assert delivery.attempt_count == 1
