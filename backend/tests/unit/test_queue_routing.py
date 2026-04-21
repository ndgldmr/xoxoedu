"""Unit tests for Celery queue routing and task configuration.

Verifies that:
- Every task is routed to its intended queue via ``task_routes``.
- All fire-and-forget tasks have ``ignore_result=True`` so Celery does not
  write unused result records to Redis.
- The announcement dispatch correctly fans out into fixed-size batches.
"""

from unittest.mock import MagicMock, patch

# Force task registration — autodiscover_tasks is lazy until the worker boots,
# so we import each task module explicitly to populate celery_app.tasks.
import app.modules.admin.tasks  # noqa: F401
import app.modules.ai.tasks  # noqa: F401
import app.modules.auth.tasks  # noqa: F401
import app.modules.certificates.tasks  # noqa: F401
import app.modules.notifications.tasks  # noqa: F401
import app.modules.rag.tasks  # noqa: F401
import app.modules.video.tasks  # noqa: F401
from app.worker.celery_app import celery_app

# ── Expected routing ───────────────────────────────────────────────────────────

TASK_QUEUE_MAP: dict[str, str] = {
    "app.modules.auth.tasks.send_verification_email": "critical",
    "app.modules.auth.tasks.send_password_reset_email": "critical",
    "app.modules.notifications.tasks.send_notification_email": "critical",
    "app.modules.admin.tasks.send_announcement_emails": "bulk_email",
    "app.modules.admin.tasks.send_announcement_email_batch": "bulk_email",
    "app.modules.ai.tasks.log_ai_usage": "ai",
    "app.modules.ai.tasks.generate_quiz_feedback": "ai",
    "app.modules.video.tasks.generate_transcript": "media",
    "app.modules.certificates.tasks.generate_certificate_pdf": "media",
    "app.modules.rag.tasks.index_lesson": "indexing",
}

FIRE_AND_FORGET_TASKS: list[str] = list(TASK_QUEUE_MAP.keys())


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve_queue(task_name: str) -> str:
    """Resolve the configured queue for a task name from ``task_routes``."""
    routes = celery_app.conf.task_routes
    if isinstance(routes, dict):
        route = routes.get(task_name)
        if isinstance(route, dict):
            return route.get("queue", celery_app.conf.task_default_queue)
    return celery_app.conf.task_default_queue


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_every_task_routes_to_correct_queue() -> None:
    """task_routes maps each task to its intended named queue."""
    for task_name, expected_queue in TASK_QUEUE_MAP.items():
        resolved = _resolve_queue(task_name)
        assert resolved == expected_queue, (
            f"{task_name!r}: expected queue {expected_queue!r}, got {resolved!r}"
        )


def test_fire_and_forget_tasks_have_ignore_result() -> None:
    """All fire-and-forget tasks must set ignore_result=True."""
    for task_name in FIRE_AND_FORGET_TASKS:
        task = celery_app.tasks.get(task_name)
        assert task is not None, f"Task {task_name!r} not registered — check autodiscover_tasks"
        assert task.ignore_result is True, (
            f"{task_name!r} should have ignore_result=True; "
            "its result is never polled and wastes Redis storage"
        )


def test_default_queue_is_critical_not_dead() -> None:
    """Unrouted tasks fall to critical so they execute rather than queue silently.

    task_default_queue must not be a queue with no consumer.  Setting it to
    'critical' means a route typo or a new task without an explicit entry
    is immediately visible in logs rather than accumulating in a dead queue.
    """
    assert celery_app.conf.task_default_queue == "critical"


def test_critical_tasks_have_explicit_routes() -> None:
    """Transactional email tasks must have explicit critical routes."""
    routes = celery_app.conf.task_routes
    assert isinstance(routes, dict)
    for task_name in [
        "app.modules.auth.tasks.send_verification_email",
        "app.modules.auth.tasks.send_password_reset_email",
        "app.modules.notifications.tasks.send_notification_email",
    ]:
        assert task_name in routes, (
            f"{task_name!r} has no explicit task_routes entry"
        )
        assert routes[task_name].get("queue") == "critical"


def test_media_and_critical_are_on_different_queues() -> None:
    """Transcription must not share a queue with password-reset email."""
    assert _resolve_queue("app.modules.video.tasks.generate_transcript") != \
           _resolve_queue("app.modules.auth.tasks.send_password_reset_email")


# ── Announcement fan-out ───────────────────────────────────────────────────────

def test_announcement_dispatch_fans_out_into_batches() -> None:
    """send_announcement_emails enqueues one batch task per 50 recipients."""
    from app.modules.admin.tasks import _BATCH_SIZE, send_announcement_emails

    recipients = [f"user{i}@example.com" for i in range(130)]
    expected_batches = -(-len(recipients) // _BATCH_SIZE)  # ceiling division → 3

    with patch(
        "app.modules.admin.tasks.send_announcement_email_batch.delay"
    ) as mock_batch:
        # Run synchronously (bypass Celery broker)
        send_announcement_emails.run(
            "ann-id-123",
            recipients,
            "Test Title",
            "Test body",
        )

    assert mock_batch.call_count == expected_batches


def test_announcement_dispatch_passes_correct_batches() -> None:
    """Each batch task receives at most _BATCH_SIZE recipients."""
    from app.modules.admin.tasks import _BATCH_SIZE, send_announcement_emails

    recipients = [f"u{i}@x.com" for i in range(110)]

    with patch(
        "app.modules.admin.tasks.send_announcement_email_batch.delay"
    ) as mock_batch:
        send_announcement_emails.run("ann-id", recipients, "Title", "Body")

    call_batches = [call.args[1] for call in mock_batch.call_args_list]
    for batch in call_batches:
        assert len(batch) <= _BATCH_SIZE

    # All recipients appear exactly once across all batches
    all_sent = [email for batch in call_batches for email in batch]
    assert sorted(all_sent) == sorted(recipients)


def test_announcement_dispatch_handles_empty_recipient_list() -> None:
    """send_announcement_emails with no recipients enqueues no batch tasks."""
    from app.modules.admin.tasks import send_announcement_emails

    with patch(
        "app.modules.admin.tasks.send_announcement_email_batch.delay"
    ) as mock_batch:
        send_announcement_emails.run("ann-id", [], "Title", "Body")

    mock_batch.assert_not_called()


def test_announcement_batch_skips_guarded_recipients() -> None:
    """send_announcement_email_batch skips recipients whose guard key is set."""
    from app.modules.admin.tasks import send_announcement_email_batch

    ann_id = "ann-abc"
    emails = ["a@x.com", "b@x.com", "c@x.com"]

    mock_rdb = MagicMock()
    # Simulate "a@x.com" already sent — its guard key exists
    mock_rdb.exists.side_effect = lambda key: "a@x.com" in key

    with (
        patch("redis.from_url", return_value=mock_rdb),
        patch("app.worker.email.send_email") as mock_send_email,
    ):
        send_announcement_email_batch.run(ann_id, emails, "Title", "Body")

    sent_to = [call.kwargs.get("to") or call.args[0] for call in mock_send_email.call_args_list]
    assert "a@x.com" not in sent_to, "guarded recipient must be skipped"
    assert "b@x.com" in sent_to
    assert "c@x.com" in sent_to
