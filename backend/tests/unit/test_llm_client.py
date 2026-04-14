"""Unit tests for LLMClient retry logic, circuit breaker, and context truncation."""

from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from app.core.exceptions import AIUnavailable
from app.modules.ai.client import LLMClient, _CircuitBreaker, _CircuitState


# ── Circuit breaker ────────────────────────────────────────────────────────────

async def test_circuit_starts_closed() -> None:
    cb = _CircuitBreaker()
    assert cb.state == _CircuitState.CLOSED
    assert not cb.is_open()


async def test_circuit_opens_after_threshold() -> None:
    cb = _CircuitBreaker(failure_threshold=5)
    for _ in range(5):
        await cb.record_failure()
    assert cb.is_open()


async def test_circuit_does_not_open_below_threshold() -> None:
    cb = _CircuitBreaker(failure_threshold=5)
    for _ in range(4):
        await cb.record_failure()
    assert not cb.is_open()


async def test_circuit_closes_after_success() -> None:
    cb = _CircuitBreaker(failure_threshold=2)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.is_open()
    await cb.record_success()
    assert cb.state == _CircuitState.CLOSED


async def test_circuit_half_open_after_reset_timeout() -> None:
    """Circuit transitions to HALF_OPEN once reset_timeout elapses."""
    from datetime import UTC, datetime, timedelta

    cb = _CircuitBreaker(failure_threshold=1, reset_timeout=60.0)
    await cb.record_failure()
    assert cb.is_open()

    # Backdate last_failure_at so the timeout appears elapsed
    cb._last_failure_at = datetime.now(UTC) - timedelta(seconds=61)
    assert cb.state == _CircuitState.HALF_OPEN
    assert not cb.is_open()


# ── Retry logic ────────────────────────────────────────────────────────────────

async def test_retries_on_rate_limit_error() -> None:
    """LLMClient calls litellm exactly 3 times before raising AIUnavailable."""
    client = LLMClient()

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = litellm.RateLimitError(
            message="rate limit", llm_provider="google", model="gemini"
        )
        with pytest.raises(AIUnavailable):
            await client.complete([{"role": "user", "content": "hello"}])

    assert mock_call.call_count == 3


async def test_retries_on_service_unavailable() -> None:
    """ServiceUnavailableError also triggers the retry policy."""
    client = LLMClient()

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = litellm.ServiceUnavailableError(
            message="down", llm_provider="google", model="gemini"
        )
        with pytest.raises(AIUnavailable):
            await client.complete([{"role": "user", "content": "hello"}])

    assert mock_call.call_count == 3


async def test_open_circuit_skips_litellm_call() -> None:
    """When the circuit is open, complete() raises without calling litellm."""
    client = LLMClient()
    # Force circuit open
    for _ in range(5):
        await client._circuit.record_failure()

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_call:
        with pytest.raises(AIUnavailable):
            await client.complete([{"role": "user", "content": "hello"}])

    mock_call.assert_not_called()


async def test_successful_call_returns_response() -> None:
    """A successful call returns a populated LLMResponse."""
    client = LLMClient()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Great answer!"
    mock_response.usage.prompt_tokens = 20
    mock_response.usage.completion_tokens = 10
    mock_response.model = "gemini/gemini-2.0-flash"

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await client.complete([{"role": "user", "content": "hello"}])

    assert result.content == "Great answer!"
    assert result.tokens_in == 20
    assert result.tokens_out == 10


async def test_successful_call_closes_circuit() -> None:
    """A successful call resets the circuit breaker failure count."""
    client = LLMClient()
    for _ in range(3):
        await client._circuit.record_failure()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"
    mock_response.usage.prompt_tokens = 5
    mock_response.usage.completion_tokens = 3
    mock_response.model = "gemini/gemini-2.0-flash"

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        await client.complete([{"role": "user", "content": "test"}])

    assert client._circuit.state == _CircuitState.CLOSED


# ── Token estimation and context truncation ────────────────────────────────────

def test_estimate_tokens_fallback() -> None:
    """Falls back to character-based estimate when litellm raises."""
    client = LLMClient()
    messages = [{"role": "user", "content": "a" * 400}]

    with patch("litellm.token_counter", side_effect=Exception("unknown model")):
        estimate = client.estimate_tokens(messages)

    # 400 chars / 4 = 100 tokens
    assert estimate == 100


def test_estimate_tokens_uses_litellm() -> None:
    client = LLMClient()
    messages = [{"role": "user", "content": "hello"}]

    with patch("litellm.token_counter", return_value=7) as mock_counter:
        estimate = client.estimate_tokens(messages)

    assert estimate == 7
    mock_counter.assert_called_once()


def test_truncation_not_applied_when_under_limit() -> None:
    """Messages within the context window are returned unchanged."""
    client = LLMClient()
    messages = [{"role": "user", "content": "short"}]

    with patch("litellm.get_max_tokens", return_value=8192):
        with patch.object(client, "estimate_tokens", return_value=100):
            result = client._truncate_to_context(messages)

    assert result[0]["content"] == "short"


def test_truncation_shortens_last_user_message() -> None:
    """Long user messages are trimmed to fit within the context window."""
    client = LLMClient()
    long_content = "x" * 10_000
    messages = [{"role": "user", "content": long_content}]

    with patch("litellm.get_max_tokens", return_value=100):
        # estimate_tokens uses the fallback: len/4, so 10000/4 = 2500 > 90
        result = client._truncate_to_context(messages)

    assert len(result[0]["content"]) < len(long_content)


def test_truncation_preserves_system_message() -> None:
    """System messages are not modified during truncation."""
    client = LLMClient()
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "x" * 10_000},
    ]

    with patch("litellm.get_max_tokens", return_value=100):
        result = client._truncate_to_context(messages)

    assert result[0]["content"] == "system prompt"
