"""Unit tests for Sprint A2 — RabbitMQ broker configuration.

Verifies that the Celery app is configured for a dedicated broker (separate
from app-side Redis), with the reliability settings required by RabbitMQ:
publisher confirms, heartbeat, connection retry, and durable queue declarations.

These tests run without a live broker — they inspect celery_app.conf directly.
"""

import pytest

from app.worker.celery_app import celery_app

# Force task registration so queue declarations are applied.
import app.modules.admin.tasks  # noqa: F401
import app.modules.ai.tasks  # noqa: F401
import app.modules.auth.tasks  # noqa: F401
import app.modules.certificates.tasks  # noqa: F401
import app.modules.rag.tasks  # noqa: F401
import app.modules.video.tasks  # noqa: F401

EXPECTED_QUEUES = {"critical", "bulk_email", "ai", "media", "indexing"}


# ── Broker / backend separation ────────────────────────────────────────────────

def test_celery_broker_url_setting_exists() -> None:
    """CELERY_BROKER_URL is a distinct setting from REDIS_URL."""
    from app.config import Settings
    fields = Settings.model_fields
    assert "CELERY_BROKER_URL" in fields
    assert "CELERY_RESULT_BACKEND" in fields


def test_celery_broker_url_defaults_to_empty_string() -> None:
    """CELERY_BROKER_URL defaults to '' so fallback logic in celery_app.py applies."""
    from app.config import Settings
    field = Settings.model_fields["CELERY_BROKER_URL"]
    assert field.default == ""


def test_celery_result_backend_defaults_to_empty_string() -> None:
    """CELERY_RESULT_BACKEND defaults to '' so fallback logic in celery_app.py applies."""
    from app.config import Settings
    field = Settings.model_fields["CELERY_RESULT_BACKEND"]
    assert field.default == ""


# ── RabbitMQ reliability settings ─────────────────────────────────────────────

def test_publisher_confirms_enabled() -> None:
    """confirm_publish must be True so .delay() blocks until RabbitMQ ACKs."""
    transport_opts = celery_app.conf.broker_transport_options or {}
    assert transport_opts.get("confirm_publish") is True, (
        "broker_transport_options['confirm_publish'] must be True — "
        "without it a broker crash between publish and persistence drops the task silently"
    )


def test_broker_heartbeat_configured() -> None:
    """AMQP heartbeat must be set to detect dead connections before the next publish."""
    assert celery_app.conf.broker_heartbeat is not None
    assert celery_app.conf.broker_heartbeat > 0


def test_broker_connection_retry_on_startup() -> None:
    """Workers must retry the broker connection on startup, not crash immediately."""
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_broker_connection_retry_enabled() -> None:
    """Broker connection retry must be enabled for mid-run reconnection."""
    assert celery_app.conf.broker_connection_retry is True


def test_task_publish_retry_enabled() -> None:
    """task_publish_retry must be True so enqueue attempts survive transient broker errors."""
    assert celery_app.conf.task_publish_retry is True


def test_task_publish_retry_policy_configured() -> None:
    """Publish retry policy must bound max_retries to avoid infinite blocking."""
    policy = celery_app.conf.task_publish_retry_policy or {}
    assert "max_retries" in policy
    assert isinstance(policy["max_retries"], int)
    assert policy["max_retries"] > 0


# ── Durable queue declarations ─────────────────────────────────────────────────

def test_all_named_queues_declared() -> None:
    """All five named queues must be explicitly declared (required for DLX in Sprint A3)."""
    declared = {q.name for q in (celery_app.conf.task_queues or [])}
    missing = EXPECTED_QUEUES - declared
    assert not missing, f"Queues not declared in task_queues: {missing}"


def test_all_declared_queues_are_durable() -> None:
    """Every declared queue must be durable so it survives broker restarts."""
    for queue in celery_app.conf.task_queues or []:
        if queue.name in EXPECTED_QUEUES:
            assert queue.durable is True, (
                f"Queue {queue.name!r} is not durable — "
                "messages will be lost on broker restart"
            )


def test_no_undeclared_routed_queues() -> None:
    """Every queue referenced in task_routes must have an explicit declaration."""
    declared = {q.name for q in (celery_app.conf.task_queues or [])}
    routes = celery_app.conf.task_routes or {}
    routed_queues = {v["queue"] for v in routes.values() if isinstance(v, dict) and "queue" in v}
    undeclared = routed_queues - declared
    assert not undeclared, (
        f"Queues in task_routes but not in task_queues: {undeclared} — "
        "add an explicit Queue() declaration for each"
    )
