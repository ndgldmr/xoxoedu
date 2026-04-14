"""LLM client with retry logic and circuit breaker.

Wraps ``litellm.acompletion`` so all call sites use a single, consistent
interface.  The circuit breaker prevents cascading timeouts when the provider
is down; tenacity handles per-call transient failures before the breaker ever
sees them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.core.exceptions import AIUnavailable

# Errors that warrant a retry — transient provider issues.
_RETRYABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.Timeout,
)

# Leave 10 % headroom so the model can always produce output tokens.
_CONTEXT_SAFETY_FACTOR = 0.9


@dataclass
class LLMResponse:
    """Structured result returned by ``LLMClient.complete``.

    Attributes:
        content: The model's text response.
        tokens_in: Prompt token count as reported by the provider.
        tokens_out: Completion token count as reported by the provider.
        model: Full model identifier used for the call.
    """

    content: str
    tokens_in: int
    tokens_out: int
    model: str


# ── Circuit breaker ────────────────────────────────────────────────────────────

class _CircuitState(StrEnum):
    CLOSED = "closed"      # Normal — calls pass through.
    OPEN = "open"          # Provider is down — short-circuit immediately.
    HALF_OPEN = "half_open"  # Cooldown elapsed — test one call.


class _CircuitBreaker:
    """Simple async-safe circuit breaker.

    Opens after ``failure_threshold`` consecutive final failures (i.e. failures
    that survived all tenacity retries).  Transitions to HALF_OPEN after
    ``reset_timeout`` seconds, allowing one test call through.  A successful
    test closes the circuit; another failure re-opens it.

    Args:
        failure_threshold: Consecutive failures required to open the circuit.
        reset_timeout: Seconds to wait in OPEN state before trying HALF_OPEN.
    """

    def __init__(
        self, failure_threshold: int = 5, reset_timeout: float = 60.0
    ) -> None:
        self._state = _CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_at: datetime | None = None
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._lock = asyncio.Lock()

    @property
    def state(self) -> _CircuitState:
        """Current circuit state, automatically transitioning OPEN → HALF_OPEN."""
        if (
            self._state == _CircuitState.OPEN
            and self._last_failure_at is not None
            and (datetime.now(UTC) - self._last_failure_at).total_seconds()
            >= self._reset_timeout
        ):
            return _CircuitState.HALF_OPEN
        return self._state

    def is_open(self) -> bool:
        """Return ``True`` only when the circuit is fully OPEN (not HALF_OPEN)."""
        return self.state == _CircuitState.OPEN

    async def record_success(self) -> None:
        """Reset failure count and close the circuit."""
        async with self._lock:
            self._failure_count = 0
            self._state = _CircuitState.CLOSED

    async def record_failure(self) -> None:
        """Increment failure count; open circuit if threshold is reached."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_at = datetime.now(UTC)
            if self._failure_count >= self._failure_threshold:
                self._state = _CircuitState.OPEN


# ── LLM client ─────────────────────────────────────────────────────────────────

class LLMClient:
    """Async LLM client with retry, circuit breaker, and context-window guard.

    Model is configured via ``settings.AI_MODEL``; provider API key via
    ``settings.GOOGLE_AI_API_KEY``.  Swapping providers requires only an env
    var change — no call-site edits.
    """

    def __init__(self) -> None:
        self._model = settings.AI_MODEL
        self._circuit = _CircuitBreaker()

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Call the LLM and return a structured response.

        Checks the circuit breaker first, then truncates the prompt if it
        exceeds the context window, then calls the provider with retry logic.

        Args:
            messages: OpenAI-style message list
                (``[{"role": "system", "content": "..."}, ...]``).
            temperature: Sampling temperature (default ``0.7``).
            max_tokens: Optional hard cap on output tokens.

        Returns:
            ``LLMResponse`` containing the text reply and token usage.

        Raises:
            AIUnavailable: If the circuit is open or all retries are exhausted.
        """
        if self._circuit.is_open():
            raise AIUnavailable()

        messages = self._truncate_to_context(messages)

        try:
            response = await self._call_with_retry(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            await self._circuit.record_success()
            return response
        except Exception as exc:
            await self._circuit.record_failure()
            raise AIUnavailable() from exc

    def estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        """Estimate the prompt token count for the given messages.

        Falls back to a character-based heuristic (1 token ≈ 4 chars) if the
        litellm counter raises (e.g. unknown model).

        Args:
            messages: OpenAI-style message list.

        Returns:
            Estimated token count.
        """
        try:
            return litellm.token_counter(model=self._model, messages=messages)
        except Exception:
            return sum(len(m.get("content", "")) for m in messages) // 4

    def _truncate_to_context(
        self, messages: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Shorten the last user message if the prompt exceeds the context window.

        Preserves all other messages intact.  Truncation is iterative: the
        last user message is shrunk by 10 % per iteration until the estimate
        fits or the content is reduced to a minimum of 100 characters.

        Args:
            messages: OpenAI-style message list.

        Returns:
            The (possibly truncated) message list.
        """
        try:
            max_ctx = litellm.get_max_tokens(self._model) or 8192
        except Exception:
            max_ctx = 8192

        limit = int(max_ctx * _CONTEXT_SAFETY_FACTOR)
        if self.estimate_tokens(messages) <= limit:
            return messages

        messages = [m.copy() for m in messages]
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                content = messages[i]["content"]
                while self.estimate_tokens(messages) > limit and len(content) > 100:
                    content = content[: int(len(content) * 0.9)]
                    messages[i]["content"] = content
                break
        return messages

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        reraise=True,
    )
    async def _call_with_retry(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if settings.GEMINI_API_KEY:
            kwargs["api_key"] = settings.GEMINI_API_KEY

        response = await litellm.acompletion(**kwargs)

        content = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            content=content,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            model=response.model or self._model,
        )


# Module-level singleton — imported by all feature modules.
llm_client = LLMClient()
