"""Redis-backed AI quota enforcement.

Each user gets a monthly request counter keyed by ``ai:quota:{user_id}:{YYYY-MM}``.
The counter is incremented atomically *before* the LLM call so budget overruns
never result in unnecessary API spend.  If the increment would push the user
over budget, the reservation is released with a matching DECR.

Callers should also fire ``log_ai_usage`` (Celery task) after a successful call
to persist the accurate token counts to Postgres.
"""

import uuid
from datetime import UTC, datetime

from app.core.exceptions import AIQuotaExceeded
from app.core.redis import get_redis


def _quota_key(user_id: str) -> str:
    month = datetime.now(UTC).strftime("%Y-%m")
    return f"ai:quota:{user_id}:{month}"


async def check_and_consume(user_id: uuid.UUID, budget: int) -> int:
    """Reserve one AI request against the user's monthly budget.

    Atomically increments the Redis counter.  If the new value exceeds
    ``budget``, the increment is reversed and ``AIQuotaExceeded`` is raised.
    On first use in a month the key TTL is set to 35 days so it expires
    naturally after the month rolls over.

    Args:
        user_id: The user consuming quota.
        budget: Maximum requests allowed this month.

    Returns:
        Remaining requests for the month after this reservation.

    Raises:
        AIQuotaExceeded: If ``budget`` has been reached.
    """
    r = get_redis()
    key = _quota_key(str(user_id))

    new_count: int = await r.incr(key)

    if new_count == 1:
        # New key — expire after 35 days to survive any month boundary
        await r.expire(key, 35 * 24 * 3600)

    if new_count > budget:
        await r.decr(key)
        raise AIQuotaExceeded()

    return budget - new_count


async def get_remaining(user_id: uuid.UUID, budget: int) -> int:
    """Return the number of AI requests remaining without consuming quota.

    Args:
        user_id: The user to check.
        budget: Maximum requests allowed this month.

    Returns:
        Remaining requests (0 if already at or over budget).
    """
    r = get_redis()
    key = _quota_key(str(user_id))
    raw = await r.get(key)
    count = int(raw) if raw else 0
    return max(0, budget - count)
