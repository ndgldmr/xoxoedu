"""Unit tests for Redis-backed AI quota enforcement."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AIQuotaExceeded
from app.modules.ai.quota import check_and_consume, get_remaining


def _mock_redis(incr_value: int, get_value: str | None = None) -> MagicMock:
    """Build a mock Redis client for quota tests."""
    r = MagicMock()
    r.incr = AsyncMock(return_value=incr_value)
    r.decr = AsyncMock(return_value=incr_value - 1)
    r.expire = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=get_value)
    return r


# ── check_and_consume ──────────────────────────────────────────────────────────

async def test_under_budget_returns_remaining() -> None:
    """First request against a budget of 100 returns 99 remaining."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=1, get_value=None)

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        remaining = await check_and_consume(user_id, budget=100)

    assert remaining == 99


async def test_first_use_sets_expiry() -> None:
    """On the first request of a month, expire is called to schedule cleanup."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=1)

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        await check_and_consume(user_id, budget=100)

    mock_r.expire.assert_awaited_once()


async def test_subsequent_use_skips_expiry() -> None:
    """expire is only set on the first increment (new_count == 1)."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=50)  # not the first call

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        await check_and_consume(user_id, budget=100)

    mock_r.expire.assert_not_awaited()


async def test_at_budget_limit_raises_quota_exceeded() -> None:
    """Request that would exceed the budget raises AIQuotaExceeded."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=101)  # over budget of 100

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        with pytest.raises(AIQuotaExceeded):
            await check_and_consume(user_id, budget=100)


async def test_over_budget_decrements_counter() -> None:
    """When quota is exceeded, the reservation is released with DECR."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=101)

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        with pytest.raises(AIQuotaExceeded):
            await check_and_consume(user_id, budget=100)

    mock_r.decr.assert_awaited_once()


async def test_response_header_value_is_zero_at_limit() -> None:
    """At exactly the budget limit the remaining count is 0."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=100)

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        remaining = await check_and_consume(user_id, budget=100)

    assert remaining == 0


# ── get_remaining ──────────────────────────────────────────────────────────────

async def test_get_remaining_no_prior_usage() -> None:
    """User with no prior usage returns full budget."""
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=0, get_value=None)

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        remaining = await get_remaining(user_id, budget=100)

    assert remaining == 100


async def test_get_remaining_with_prior_usage() -> None:
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=0, get_value="30")

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        remaining = await get_remaining(user_id, budget=100)

    assert remaining == 70


async def test_get_remaining_at_or_over_budget_returns_zero() -> None:
    user_id = uuid.uuid4()
    mock_r = _mock_redis(incr_value=0, get_value="105")

    with patch("app.modules.ai.quota.get_redis", return_value=mock_r):
        remaining = await get_remaining(user_id, budget=100)

    assert remaining == 0
