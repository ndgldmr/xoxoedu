"""Exponential backoff helpers for Celery task retry policies.

Each task class has a dedicated function tuned for its workload and queue:

- ``critical``  (transactional email): fast start, capped at 480 s — 5 retries
- ``bulk``      (announcement dispatch): moderate start, capped at 240 s — 3 retries
- ``ai``        (LLM calls): moderate start, longer cap for provider rate limits
- ``media``     (transcription, PDF): slow start, long cap for CPU-heavy jobs
- ``indexing``  (RAG embedding): moderate start, capped at 120 s

Usage in a task body::

    from app.worker.retry import critical_backoff

    except Exception as exc:
        raise self.retry(
            exc=exc,
            countdown=critical_backoff(self.request.retries),
        ) from exc

``self.request.retries`` is 0-indexed: it equals 0 on the first retry
attempt, 1 on the second, and so on.  ``countdown`` is the number of
seconds to wait before the next attempt.
"""

from __future__ import annotations


def _backoff(retries: int, base: int, cap: int) -> int:
    """Exponential backoff capped at *cap*.

    Args:
        retries: Zero-based retry count from ``self.request.retries``.
        base: Delay in seconds for the first retry attempt (retries=0).
        cap: Maximum delay in seconds.

    Returns:
        Seconds to wait before the next attempt.
    """
    return min(base * (2 ** retries), cap)


def critical_backoff(retries: int) -> int:
    """Backoff for critical-queue tasks (transactional email).

    Delays: 30 s → 60 s → 120 s → 240 s → 480 s (cap).
    Designed for ``max_retries=5``.
    """
    return _backoff(retries, base=30, cap=480)


def bulk_backoff(retries: int) -> int:
    """Backoff for bulk-email-queue tasks (announcement dispatch and batches).

    Delays: 60 s → 120 s → 240 s (cap).
    Designed for ``max_retries=3``.
    """
    return _backoff(retries, base=60, cap=240)


def ai_backoff(retries: int) -> int:
    """Backoff for ai-queue tasks (LLM calls, usage logging).

    Longer cap accommodates LLM provider rate-limit windows.
    Delays: 30 s → 60 s → 120 s → 300 s (cap).
    Designed for ``max_retries=3`` or ``max_retries=4``.
    """
    return _backoff(retries, base=30, cap=300)


def media_backoff(retries: int) -> int:
    """Backoff for media-queue tasks (transcription, certificate PDF).

    Long cap to allow time for overloaded media infrastructure to recover.
    Delays: 60 s → 120 s → 600 s (cap).
    Designed for ``max_retries=3``.
    """
    return _backoff(retries, base=60, cap=600)


def indexing_backoff(retries: int) -> int:
    """Backoff for indexing-queue tasks (RAG embedding).

    Delays: 30 s → 60 s → 120 s (cap).
    Designed for ``max_retries=3``.
    """
    return _backoff(retries, base=30, cap=120)
