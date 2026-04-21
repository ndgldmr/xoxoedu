"""Redis-backed execution metadata for user-visible async tasks.

Records started / success / failure events for async flows that users
directly observe (transcript generation, certificate PDF, quiz AI feedback)
so operators and support staff can inspect task state without tailing
worker logs or querying the Celery result backend.

Key schema:  ``task:status:<task_short_name>:<entity_id>``
Value:       JSON ``{"task_id": str, "status": str, "ts": float, "error"?: str}``
TTL:         7 days — covers any realistic retry window.

Usage in a task body::

    import redis as sync_redis
    from app.config import settings
    from app.worker.task_status import record_started, record_success, record_failure

    rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

    record_started(rdb, "transcript", lesson_id, str(self.request.id))
    # ... do work ...
    record_success(rdb, "transcript", lesson_id, str(self.request.id))
"""

from __future__ import annotations

import json
import time

_TTL = 7 * 86_400  # 7 days in seconds
_PREFIX = "task:status"


def _key(name: str, entity_id: str) -> str:
    return f"{_PREFIX}:{name}:{entity_id}"


def record_started(rdb, name: str, entity_id: str, task_id: str) -> None:
    """Write a 'started' status record.

    Safe to call on every attempt — later retries overwrite earlier records.

    Args:
        rdb: Synchronous Redis client (``redis.from_url(...)``).
        name: Short task identifier, e.g. ``"transcript"``.
        entity_id: String UUID of the entity being processed.
        task_id: Celery task ID from ``str(self.request.id)``.
    """
    rdb.set(
        _key(name, entity_id),
        json.dumps({"task_id": task_id, "status": "started", "ts": time.time()}),
        ex=_TTL,
    )


def record_success(rdb, name: str, entity_id: str, task_id: str) -> None:
    """Overwrite the record with 'success' once the task commits its result.

    Args:
        rdb: Synchronous Redis client.
        name: Short task identifier.
        entity_id: String UUID of the entity being processed.
        task_id: Celery task ID from ``str(self.request.id)``.
    """
    rdb.set(
        _key(name, entity_id),
        json.dumps({"task_id": task_id, "status": "success", "ts": time.time()}),
        ex=_TTL,
    )


def record_failure(rdb, name: str, entity_id: str, task_id: str, error: str) -> None:
    """Overwrite the record with 'failure' and the error message.

    Call this when ``self.request.retries >= self.max_retries`` (final failure)
    immediately before ``raise self.retry(...)`` raises ``MaxRetriesExceeded``.

    Args:
        rdb: Synchronous Redis client.
        name: Short task identifier.
        entity_id: String UUID of the entity being processed.
        task_id: Celery task ID from ``str(self.request.id)``.
        error: String representation of the exception (truncated to 500 chars).
    """
    rdb.set(
        _key(name, entity_id),
        json.dumps({
            "task_id": task_id,
            "status": "failure",
            "error": str(error)[:500],
            "ts": time.time(),
        }),
        ex=_TTL,
    )


def get_status(rdb, name: str, entity_id: str) -> dict | None:
    """Read the current status record for an entity.

    Args:
        rdb: Synchronous Redis client.
        name: Short task identifier.
        entity_id: String UUID of the entity to check.

    Returns:
        A dict with ``status``, ``task_id``, ``ts``, and optionally ``error``,
        or ``None`` if no record exists.
    """
    raw = rdb.get(_key(name, entity_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
