"""Shared async Redis client for quota enforcement and caching."""

import redis.asyncio as aioredis

from app.config import settings

_redis: aioredis.Redis | None = None  # type: ignore[type-arg]


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    """Return the module-level async Redis client, creating it on first call.

    Uses a single connection pool shared across all requests; safe to call
    repeatedly since the pool is thread/coroutine safe.

    Returns:
        An ``aioredis.Redis`` instance connected to ``settings.REDIS_URL``.
    """
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis
