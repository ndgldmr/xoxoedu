"""Unit tests for Sprint A3 — dead-letter queue configuration.

Verifies that:
- All five worker queues declare the dead_letter DLX via queue_arguments.
- The dead_letter queue itself is declared and durable.
- task_reject_on_worker_lost is enabled (so crashed workers route to DLX).
- No queue argument inconsistencies exist between declared queues and task_routes.
"""

import pytest

from app.worker.celery_app import celery_app

# Force task registration.
import app.modules.admin.tasks  # noqa: F401
import app.modules.ai.tasks  # noqa: F401
import app.modules.auth.tasks  # noqa: F401
import app.modules.certificates.tasks  # noqa: F401
import app.modules.rag.tasks  # noqa: F401
import app.modules.video.tasks  # noqa: F401
import app.worker.maintenance  # noqa: F401

WORKER_QUEUES = {"critical", "bulk_email", "ai", "media", "indexing"}
_DLX_NAME = "dead_letter"


def _get_queue(name: str):
    for q in celery_app.conf.task_queues or []:
        if q.name == name:
            return q
    return None


# ── DLX arguments on worker queues ────────────────────────────────────────────

def test_all_worker_queues_have_dlx_configured() -> None:
    """Every worker queue must declare x-dead-letter-exchange."""
    for queue_name in WORKER_QUEUES:
        queue = _get_queue(queue_name)
        assert queue is not None, f"Queue {queue_name!r} not found in task_queues"
        args = queue.queue_arguments or {}
        assert args.get("x-dead-letter-exchange") == _DLX_NAME, (
            f"Queue {queue_name!r} missing x-dead-letter-exchange={_DLX_NAME!r}; "
            f"got: {args}"
        )


def test_dlx_name_is_consistent_across_all_worker_queues() -> None:
    """All worker queues route to the same dead-letter exchange name."""
    dlx_names = set()
    for queue_name in WORKER_QUEUES:
        queue = _get_queue(queue_name)
        if queue and queue.queue_arguments:
            dlx_names.add(queue.queue_arguments.get("x-dead-letter-exchange"))
    assert len(dlx_names) == 1, (
        f"Worker queues reference different DLX names: {dlx_names}"
    )


# ── Dead-letter queue declaration ─────────────────────────────────────────────

def test_dead_letter_queue_is_declared() -> None:
    """A queue named 'dead_letter' must be in task_queues."""
    declared = {q.name for q in (celery_app.conf.task_queues or [])}
    assert _DLX_NAME in declared, (
        f"'dead_letter' queue not declared in task_queues; found: {declared}"
    )


def test_dead_letter_queue_is_durable() -> None:
    """The dead_letter queue must be durable so messages survive broker restarts."""
    queue = _get_queue(_DLX_NAME)
    assert queue is not None
    assert queue.durable is True


def test_dead_letter_queue_has_no_dlx_of_its_own() -> None:
    """The dead_letter queue must not forward to another DLX (no chaining)."""
    queue = _get_queue(_DLX_NAME)
    assert queue is not None
    args = queue.queue_arguments or {}
    assert "x-dead-letter-exchange" not in args, (
        "dead_letter queue must not forward to another DLX"
    )


# ── Worker-lost rejection ──────────────────────────────────────────────────────

def test_task_reject_on_worker_lost_is_enabled() -> None:
    """task_reject_on_worker_lost must be True so crashed workers route to DLX.

    Without this setting, a worker killed mid-task requeues the message
    instead of rejecting it, bypassing the DLX entirely.
    """
    assert celery_app.conf.task_reject_on_worker_lost is True


# ── Maintenance task routing ───────────────────────────────────────────────────

def test_maintenance_task_is_registered() -> None:
    """The beat maintenance task must be registered in celery_app.tasks."""
    task_name = "app.worker.maintenance.retry_stuck_transcriptions"
    assert task_name in celery_app.tasks, (
        f"{task_name!r} not registered — check that app.worker.maintenance is imported "
        "in celery_app.py after autodiscover_tasks"
    )


def test_maintenance_task_has_no_retries() -> None:
    """Beat tasks must have max_retries=0 — failures retry on the next tick."""
    task = celery_app.tasks.get("app.worker.maintenance.retry_stuck_transcriptions")
    assert task is not None
    assert task.max_retries == 0
