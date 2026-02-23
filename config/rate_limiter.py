"""Token-bucket rate limiter for LLM API calls.

Enforces per-model request rate limits to stay within provider quotas and
avoid 429 responses.  Supports async acquire/release and a context manager.

Usage::

    from config.rate_limiter import get_rate_limiter

    rl = get_rate_limiter()
    async with rl.throttle("claude-sonnet-4-5-20250929"):
        response = await litellm.acompletion(...)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog

log = structlog.get_logger().bind(component="rate_limiter")

# ---------------------------------------------------------------------------
# Per-model rate limits (requests per minute)
# ---------------------------------------------------------------------------

_DEFAULT_LIMITS: dict[str, float] = {
    "claude-sonnet-4-5-20250929": 50.0,
    "claude-sonnet-4-5-latest": 50.0,
    "claude-haiku-4-5-20241022": 100.0,
}

# Fallback for unknown API models; local/ollama models get 0 (unlimited)
_FALLBACK_RPM = 50.0


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Async-safe token bucket for a single model."""

    __slots__ = (
        "capacity",
        "tokens",
        "refill_rate",
        "_last_refill",
        "_event",
        "_lock",
    )

    def __init__(self, requests_per_minute: float) -> None:
        self.capacity = requests_per_minute
        self.tokens = requests_per_minute
        # Tokens added per second
        self.refill_rate = requests_per_minute / 60.0
        self._last_refill = time.monotonic()
        self._event = asyncio.Event()
        self._event.set()  # start open
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

            # No token available — wait until signalled or a short interval
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=0.5)
            except TimeoutError:
                pass  # re-check after refill

    async def release(self) -> None:
        """Return a token to the bucket (e.g. after a 429 retry-after)."""
        async with self._lock:
            self.tokens = min(self.capacity, self.tokens + 1.0)
            self._event.set()


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Per-model rate limiter using token buckets.

    Models prefixed with ``ollama/`` are treated as local and unlimited.
    Unknown API models get a default limit of 50 req/min.
    """

    def __init__(
        self,
        limits: dict[str, float] | None = None,
    ) -> None:
        self._limits: dict[str, float] = {**_DEFAULT_LIMITS, **(limits or {})}
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = asyncio.Lock()

    def _is_unlimited(self, model: str) -> bool:
        return model.startswith("ollama/")

    async def _get_bucket(self, model: str) -> _TokenBucket | None:
        """Return the bucket for *model*, creating it lazily. None for unlimited."""
        if self._is_unlimited(model):
            return None
        async with self._lock:
            if model not in self._buckets:
                rpm = self._limits.get(model, _FALLBACK_RPM)
                self._buckets[model] = _TokenBucket(rpm)
                log.debug("bucket created", model=model, rpm=rpm)
            return self._buckets[model]

    async def acquire(self, model: str) -> None:
        """Block until rate limit allows a request for *model*."""
        bucket = await self._get_bucket(model)
        if bucket is None:
            return
        await bucket.acquire()

    async def release(self, model: str) -> None:
        """Return a token — call after a 429 so the slot is reclaimed."""
        bucket = await self._get_bucket(model)
        if bucket is None:
            return
        await bucket.release()

    @asynccontextmanager
    async def throttle(self, model: str) -> AsyncIterator[None]:
        """Context manager that acquires before yield and handles release."""
        await self.acquire(model)
        try:
            yield
        except Exception:
            # On failure, give the token back so retries aren't penalised
            await self.release(model)
            raise


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_rate_limiter: RateLimiter | None = None


def get_rate_limiter(
    limits: dict[str, float] | None = None,
) -> RateLimiter:
    """Return the process-wide RateLimiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(limits)
    return _rate_limiter
