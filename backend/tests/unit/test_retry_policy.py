"""Unit tests for Sprint A3 — per-task retry policies and backoff functions.

Verifies that:
- Each backoff function produces exponential growth capped at the correct maximum.
- Every task has the correct ``max_retries``, ``soft_time_limit``, and
  ``time_limit`` values matching its task class policy.
- Task-level time limits do not exceed their worker pool limits (so decorator
  annotations are honoured rather than silently overridden by the pool).
"""

import pytest

from app.worker.retry import (
    ai_backoff,
    bulk_backoff,
    critical_backoff,
    indexing_backoff,
    media_backoff,
)
from app.worker.celery_app import celery_app

# Force task registration before inspecting celery_app.tasks.
import app.modules.admin.tasks  # noqa: F401
import app.modules.ai.tasks  # noqa: F401
import app.modules.auth.tasks  # noqa: F401
import app.modules.certificates.tasks  # noqa: F401
import app.modules.rag.tasks  # noqa: F401
import app.modules.video.tasks  # noqa: F401
import app.worker.maintenance  # noqa: F401


# ── Backoff function tests ─────────────────────────────────────────────────────

class TestCriticalBackoff:
    def test_first_retry(self):
        assert critical_backoff(0) == 30

    def test_second_retry(self):
        assert critical_backoff(1) == 60

    def test_third_retry(self):
        assert critical_backoff(2) == 120

    def test_caps_at_480(self):
        assert critical_backoff(10) == 480

    def test_monotonically_increasing(self):
        delays = [critical_backoff(i) for i in range(6)]
        assert delays == sorted(delays)

    def test_always_positive(self):
        for i in range(10):
            assert critical_backoff(i) > 0


class TestBulkBackoff:
    def test_first_retry(self):
        assert bulk_backoff(0) == 60

    def test_second_retry(self):
        assert bulk_backoff(1) == 120

    def test_caps_at_240(self):
        assert bulk_backoff(10) == 240

    def test_monotonically_increasing(self):
        delays = [bulk_backoff(i) for i in range(4)]
        assert delays == sorted(delays)


class TestAiBackoff:
    def test_first_retry(self):
        assert ai_backoff(0) == 30

    def test_caps_at_300(self):
        assert ai_backoff(10) == 300

    def test_monotonically_increasing(self):
        delays = [ai_backoff(i) for i in range(5)]
        assert delays == sorted(delays)


class TestMediaBackoff:
    def test_first_retry(self):
        assert media_backoff(0) == 60

    def test_second_retry(self):
        assert media_backoff(1) == 120

    def test_caps_at_600(self):
        assert media_backoff(10) == 600

    def test_monotonically_increasing(self):
        delays = [media_backoff(i) for i in range(4)]
        assert delays == sorted(delays)


class TestIndexingBackoff:
    def test_first_retry(self):
        assert indexing_backoff(0) == 30

    def test_caps_at_120(self):
        assert indexing_backoff(10) == 120

    def test_monotonically_increasing(self):
        delays = [indexing_backoff(i) for i in range(4)]
        assert delays == sorted(delays)


# ── Task max_retries ───────────────────────────────────────────────────────────

TASK_MAX_RETRIES: dict[str, int] = {
    # critical — 5 retries to account for transient email provider outages
    "app.modules.auth.tasks.send_verification_email": 5,
    "app.modules.auth.tasks.send_password_reset_email": 5,
    # bulk — 3 retries; duplicate guards ensure safe re-enqueue
    "app.modules.admin.tasks.send_announcement_emails": 3,
    "app.modules.admin.tasks.send_announcement_email_batch": 3,
    # ai — 3 retries; log_ai_usage is diagnostic, capped to avoid slot starvation
    "app.modules.ai.tasks.log_ai_usage": 3,
    "app.modules.ai.tasks.generate_quiz_feedback": 3,
    # media — 3 retries; long backoff gives infrastructure time to recover
    "app.modules.video.tasks.generate_transcript": 3,
    "app.modules.certificates.tasks.generate_certificate_pdf": 3,
    # indexing — 3 retries; task is idempotent (delete + re-insert)
    "app.modules.rag.tasks.index_lesson": 3,
}


def test_every_task_has_correct_max_retries() -> None:
    """Each task's max_retries matches its intended policy."""
    for task_name, expected in TASK_MAX_RETRIES.items():
        task = celery_app.tasks.get(task_name)
        assert task is not None, f"Task {task_name!r} not registered"
        assert task.max_retries == expected, (
            f"{task_name!r}: expected max_retries={expected}, got {task.max_retries}"
        )


# ── Task time limits ───────────────────────────────────────────────────────────
# Decorator soft_time_limit must be strictly less than the worker pool's
# --soft-time-limit so the decorator fires first, giving cleanup time.
# Decorator time_limit must be <= the worker pool's --time-limit.
#
# Worker pool limits (from docker-compose.yml):
#   critical:  soft=20, hard=30
#   bulk_email: soft=90, hard=120
#   ai:         soft=150, hard=180
#   media:      soft=600, hard=700
#   indexing:   soft=150, hard=180

TASK_TIME_LIMITS: dict[str, tuple[int, int]] = {
    # (soft_time_limit, time_limit)
    "app.modules.auth.tasks.send_verification_email": (20, 30),
    "app.modules.auth.tasks.send_password_reset_email": (20, 30),
    "app.modules.admin.tasks.send_announcement_emails": (30, 60),
    "app.modules.admin.tasks.send_announcement_email_batch": (90, 120),
    "app.modules.ai.tasks.log_ai_usage": (15, 20),
    "app.modules.ai.tasks.generate_quiz_feedback": (150, 180),
    "app.modules.video.tasks.generate_transcript": (580, 700),
    "app.modules.certificates.tasks.generate_certificate_pdf": (55, 60),
    "app.modules.rag.tasks.index_lesson": (150, 180),
}


def test_every_task_has_correct_soft_time_limit() -> None:
    for task_name, (expected_soft, _) in TASK_TIME_LIMITS.items():
        task = celery_app.tasks.get(task_name)
        assert task is not None, f"Task {task_name!r} not registered"
        assert task.soft_time_limit == expected_soft, (
            f"{task_name!r}: expected soft_time_limit={expected_soft}, "
            f"got {task.soft_time_limit}"
        )


def test_every_task_has_correct_time_limit() -> None:
    for task_name, (_, expected_hard) in TASK_TIME_LIMITS.items():
        task = celery_app.tasks.get(task_name)
        assert task is not None, f"Task {task_name!r} not registered"
        assert task.time_limit == expected_hard, (
            f"{task_name!r}: expected time_limit={expected_hard}, "
            f"got {task.time_limit}"
        )


def test_generate_transcript_soft_limit_is_below_worker_pool_cap() -> None:
    """Transcript task soft limit (580) must be below the media worker pool cap (600)."""
    task = celery_app.tasks["app.modules.video.tasks.generate_transcript"]
    assert task.soft_time_limit < 600, (
        "generate_transcript soft_time_limit must be < 600 (the media worker pool cap); "
        "otherwise the worker fires SoftTimeLimitExceeded before the task decorator can."
    )


# ── Beat schedule ──────────────────────────────────────────────────────────────

def test_beat_schedule_contains_stuck_transcription_check() -> None:
    """The beat schedule must include the hourly stuck-transcript recovery task."""
    schedule = celery_app.conf.beat_schedule
    assert "retry-stuck-transcriptions" in schedule


def test_stuck_transcription_beat_interval_is_one_hour() -> None:
    entry = celery_app.conf.beat_schedule["retry-stuck-transcriptions"]
    assert entry["schedule"] == 3600.0


def test_stuck_transcription_beat_task_name() -> None:
    entry = celery_app.conf.beat_schedule["retry-stuck-transcriptions"]
    assert entry["task"] == "app.worker.maintenance.retry_stuck_transcriptions"
