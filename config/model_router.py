"""Unified model routing via LiteLLM.

Routes LLM requests to the appropriate provider (Anthropic API, local Ollama)
based on agent role and task complexity, with automatic fallback on failure.

Includes:
- Token-bucket rate limiting (via :mod:`config.rate_limiter`)
- Circuit breaker per model (5 failures in 2 min → open for 60 s)
- Error-type-aware retry (429, 5xx, timeout, content-filter, auth)
- DEBUG request/response logging (no message content)

Usage::

    from config.model_router import get_model_router

    router = get_model_router()
    model = await router.route_request("architect")
    response = await router.complete(model, messages=[...])
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque

import structlog

log = structlog.get_logger().bind(component="model_router")

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens)
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    # model_id: (input_per_mtok, output_per_mtok)
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20241022": (1.00, 5.00),
    "ollama/qwen2.5-coder:32b": (0.00, 0.00),
}

# ---------------------------------------------------------------------------
# Default route definitions
# ---------------------------------------------------------------------------

_DEFAULT_ROUTES: dict[str, str] = {
    "frontier": "claude-sonnet-4-5-20250929",
    "strong": "claude-sonnet-4-5-20250929",
    "local_coder": "ollama/qwen2.5-coder:32b",
    "local_coder_fallback": "claude-sonnet-4-5-20250929",
}

# Maps agent roles to route tiers
_ROLE_TO_TIER: dict[str, str] = {
    "architect": "frontier",
    "qa": "frontier",
    "qa_engineer": "frontier",
    "cto": "frontier",
    "business_analyst": "strong",
    "product_manager": "strong",
    "researcher": "strong",
    "research_analyst": "strong",
    "pm": "strong",
    "ticket_manager": "strong",
    "developer": "local_coder",
    "engineer": "local_coder",
}

# ---------------------------------------------------------------------------
# Non-retryable error classification
# ---------------------------------------------------------------------------

_CONTENT_FILTER_MARKERS = ("content_filter", "content_policy", "content moderation")
_AUTH_ERROR_MARKERS = ("authentication", "auth", "invalid_api_key", "permission")


def _classify_error(exc: Exception) -> str:
    """Return a category string for *exc* to drive retry/abort decisions.

    Categories:
    - ``"rate_limit"`` — 429 Too Many Requests
    - ``"server_error"`` — 500 / 502 / 503
    - ``"timeout"`` — request timed out
    - ``"content_filter"`` — content moderation rejection
    - ``"auth"`` — authentication / permission error
    - ``"unknown"`` — anything else
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

    if status == 429 or "rate_limit" in msg or "429" in msg:
        return "rate_limit"
    if status in (500, 502, 503) or "server_error" in msg or "overloaded" in msg:
        return "server_error"
    if "timeout" in name or "timeout" in msg or isinstance(exc, TimeoutError):
        return "timeout"
    for marker in _CONTENT_FILTER_MARKERS:
        if marker in msg:
            return "content_filter"
    for marker in _AUTH_ERROR_MARKERS:
        if marker in name or marker in msg:
            return "auth"
    return "unknown"


def _get_retry_after(exc: Exception) -> float | None:
    """Extract ``Retry-After`` seconds from a 429 response if available."""
    headers = getattr(exc, "headers", None) or {}
    if isinstance(headers, dict):
        val = headers.get("retry-after") or headers.get("Retry-After")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    # LiteLLM sometimes embeds it in the message
    msg = str(exc)
    for token in msg.split():
        if token.replace(".", "", 1).isdigit():
            v = float(token)
            if 0 < v < 300:
                return v
    return None


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Per-model circuit breaker.

    Opens after *failure_threshold* failures within *window_seconds*,
    then stays open for *recovery_seconds* before moving to half-open
    (one probe request allowed).
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: float = 120.0,
        recovery_seconds: float = 60.0,
    ) -> None:
        self._threshold = failure_threshold
        self._window = window_seconds
        self._recovery = recovery_seconds
        # model → deque of failure timestamps
        self._failures: dict[str, deque[float]] = {}
        # model → time when circuit opened
        self._open_since: dict[str, float] = {}

    def is_open(self, model: str) -> bool:
        opened = self._open_since.get(model)
        if opened is None:
            return False
        elapsed = time.monotonic() - opened
        if elapsed >= self._recovery:
            # Move to half-open: clear state and allow one probe
            self._open_since.pop(model, None)
            self._failures.pop(model, None)
            log.info("circuit half-open, probing", model=model)
            return False
        return True

    def record_failure(self, model: str) -> None:
        now = time.monotonic()
        dq = self._failures.setdefault(model, deque())
        dq.append(now)
        # Evict old entries outside the window
        cutoff = now - self._window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self._threshold:
            self._open_since[model] = now
            log.warning(
                "circuit opened",
                model=model,
                failures=len(dq),
                window_s=self._window,
            )

    def record_success(self, model: str) -> None:
        # Success in half-open fully closes the circuit
        self._open_since.pop(model, None)
        self._failures.pop(model, None)


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Route LLM calls based on agent role and task characteristics.

    Wraps LiteLLM to provide:
    - Role-based model selection (frontier / strong / local_coder tiers)
    - Local model availability detection (Ollama health check)
    - Automatic fallback on failure (local -> API, strong -> frontier)
    - Token-bucket rate limiting
    - Per-model circuit breaker
    - Error-type-aware retry with back-off
    - Cost tracking and latency measurement
    """

    def __init__(self, config: dict | None = None) -> None:
        routes = config or {}
        self._routes: dict[str, str] = {**_DEFAULT_ROUTES, **routes}
        self._local_available: bool | None = None
        self._local_check_time: float = 0.0
        self._local_cache_ttl: float = 60.0
        self._circuit_breaker = CircuitBreaker()

    # ------------------------------------------------------------------
    # Local model availability
    # ------------------------------------------------------------------

    async def check_local_model_available(self) -> bool:
        """Ping Ollama to check if qwen2.5-coder:32b is available.

        Caches the result for 60 seconds to avoid repeated HTTP calls.
        """
        now = time.monotonic()
        cache_valid = (
            self._local_available is not None
            and (now - self._local_check_time) < self._local_cache_ttl
        )
        if cache_valid:
            return self._local_available

        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check Ollama is running
                resp = await client.get(f"{ollama_url}/api/tags")
                if resp.status_code != 200:
                    self._local_available = False
                    self._local_check_time = now
                    return False

                # Check if the model is pulled
                data = resp.json()
                model_names = [m.get("name", "") for m in data.get("models", [])]
                self._local_available = any(
                    "qwen2.5-coder" in name and "32b" in name for name in model_names
                )
        except Exception:
            self._local_available = False

        self._local_check_time = now
        log.debug(
            "local model check",
            available=self._local_available,
            ollama_url=ollama_url,
        )
        return self._local_available

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def route_request(
        self,
        agent_role: str,
        task_complexity: str = "medium",
    ) -> str:
        """Select a model based on agent role and task complexity.

        Routing logic:
        - architect, qa, cto -> always ``frontier``
        - business_analyst, researcher, pm -> always ``strong``
        - engineer/developer with complexity ``small`` -> ``local_coder`` if
          available, else ``local_coder_fallback``
        - engineer/developer with complexity ``medium`` or ``large`` -> ``strong``

        The ``FORGE_MODEL_OVERRIDE`` env var forces all requests to a
        specific model, bypassing routing.
        """
        override = os.environ.get("FORGE_MODEL_OVERRIDE")
        if override:
            log.debug("model override active", model=override, agent_role=agent_role)
            return override

        tier = _ROLE_TO_TIER.get(agent_role, "strong")

        # Engineers: complexity determines the tier
        if tier == "local_coder":
            if task_complexity in ("medium", "large"):
                tier = "strong"
            else:
                # small complexity -> try local, fall back to API
                if not await self.check_local_model_available():
                    tier = "local_coder_fallback"

        model = self._routes.get(tier, self._routes["strong"])

        log.info(
            "model routed",
            agent_role=agent_role,
            task_complexity=task_complexity,
            tier=tier,
            model=model,
        )
        return model

    # ------------------------------------------------------------------
    # Org-scoped API key resolution
    # ------------------------------------------------------------------

    @staticmethod
    async def _resolve_org_api_key(model: str) -> str | None:
        """Check the pipeline context for an org_id and look up org-specific API keys.

        Returns the API key string if found, or None to fall back to env vars.
        """
        try:
            from memory.observability import get_pipeline_context
            ctx = get_pipeline_context()
            if not ctx or not ctx.get("org_id"):
                return None

            org_id = ctx["org_id"]

            # Determine which secret key to look up based on the model provider
            if "claude" in model or "anthropic" in model:
                secret_key = "ANTHROPIC_API_KEY"
            elif "gpt" in model or "openai" in model:
                secret_key = "OPENAI_API_KEY"
            else:
                return None

            from auth.secrets import get_org_secret
            return await get_org_secret(org_id, secret_key)

        except Exception:
            # Any failure (DB not connected, table missing, etc.) — fall back
            return None

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    async def complete(
        self,
        model: str,
        messages: list[dict],
        **kwargs,
    ) -> dict:
        """Call ``litellm.acompletion`` with rate limiting, circuit breaker,
        error-aware retry, and fallback logic.

        If running within a pipeline context with an ``org_id``, checks
        org secrets for API keys (e.g. ``ANTHROPIC_API_KEY``) before
        falling back to environment variables.

        Returns a standardised dict::

            {
                "content": str,
                "model_used": str,
                "input_tokens": int,
                "output_tokens": int,
                "cost_usd": float,
                "latency_ms": float,
            }
        """
        override = os.environ.get("FORGE_MODEL_OVERRIDE")
        if override:
            model = override

        # Resolve org-specific API key if available
        org_api_key = await self._resolve_org_api_key(model)
        if org_api_key:
            kwargs["api_key"] = org_api_key

        fallback_chain = self._build_fallback_chain(model)

        last_error: Exception | None = None
        for idx, attempt_model in enumerate(fallback_chain):
            # Skip models whose circuit is open
            if self._circuit_breaker.is_open(attempt_model):
                log.info(
                    "circuit open, skipping model",
                    model=attempt_model,
                )
                continue

            # -- Stream llm.model_selected event -----------------------------
            try:
                from memory.observability import get_pipeline_context
                _ctx = get_pipeline_context()
                if _ctx and _ctx.get("pipeline_id"):
                    from memory.agent_log import stream_agent_log
                    import asyncio as _aio
                    _aio.ensure_future(stream_agent_log(
                        _ctx["pipeline_id"],
                        "llm.model_selected",
                        agent_role=_ctx.get("agent_role"),
                        stage=_ctx.get("stage"),
                        payload={
                            "model": attempt_model,
                            "is_fallback": idx > 0,
                        },
                    ))
            except Exception:
                pass

            try:
                result = await self._try_complete(
                    attempt_model,
                    messages,
                    **kwargs,
                )
                self._circuit_breaker.record_success(attempt_model)
                return result
            except Exception as exc:
                last_error = exc
                category = _classify_error(exc)
                self._circuit_breaker.record_failure(attempt_model)
                log.warning(
                    "model call failed, trying fallback",
                    model=attempt_model,
                    error_category=category,
                    error=str(exc)[:200],
                )

        # All fallbacks exhausted
        raise RuntimeError(f"All models failed. Last error: {last_error}") from last_error

    async def _try_complete(
        self,
        model: str,
        messages: list[dict],
        **kwargs,
    ) -> dict:
        """Attempt a single completion call with error-aware retries."""
        import litellm

        from config.rate_limiter import get_rate_limiter

        max_retries = 3 if model == self._routes.get("frontier") else 1
        base_delay = 1.0
        msg_count = len(messages)

        for attempt in range(max_retries):
            try:
                rl = get_rate_limiter()
                await rl.acquire(model)

                log.debug(
                    "llm request",
                    model=model,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    message_count=msg_count,
                )

                start = time.monotonic()
                response = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    **kwargs,
                )
                latency_ms = (time.monotonic() - start) * 1000

                # Extract response data
                choice = response.choices[0]
                content = choice.message.content or ""
                usage = (
                    response.usage
                    or type(
                        "U",
                        (),
                        {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                        },
                    )()
                )
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0

                cost_usd = self._calculate_cost(model, input_tokens, output_tokens)

                log.debug(
                    "llm response",
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=round(cost_usd, 6),
                    latency_ms=round(latency_ms, 1),
                )

                return {
                    "content": content,
                    "model_used": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "latency_ms": round(latency_ms, 1),
                }

            except Exception as exc:
                category = _classify_error(exc)

                # Non-retryable errors — fail immediately
                if category == "content_filter":
                    log.error(
                        "content filter rejection",
                        model=model,
                        error=str(exc)[:200],
                    )
                    raise
                if category == "auth":
                    log.error(
                        "authentication error",
                        model=model,
                        error=str(exc)[:200],
                    )
                    raise

                # Retryable errors — back off and retry
                if attempt < max_retries - 1:
                    if category == "rate_limit":
                        retry_after = _get_retry_after(exc)
                        delay = retry_after if retry_after else base_delay * (2**attempt)
                        # Return the rate-limit token so the bucket isn't starved
                        rl = get_rate_limiter()
                        await rl.release(model)
                    elif category == "timeout":
                        delay = base_delay
                    else:
                        delay = base_delay * (2**attempt)

                    log.debug(
                        "retrying model",
                        model=model,
                        attempt=attempt + 1,
                        delay=delay,
                        error_category=category,
                        error=str(exc)[:200],
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        # Unreachable, but satisfies type checker
        raise RuntimeError("retry loop exited unexpectedly")  # pragma: no cover

    def _build_fallback_chain(self, model: str) -> list[str]:
        """Build an ordered list of models to try."""
        local = self._routes.get("local_coder", "")
        local_fb = self._routes.get("local_coder_fallback", "")
        strong = self._routes.get("strong", "")
        frontier = self._routes.get("frontier", "")

        if model == local:
            return [local, local_fb]
        if model == strong:
            chain = [strong]
            if frontier != strong:
                chain.append(frontier)
            return chain
        # frontier or unknown — just use the model itself (retries handled internally)
        return [model]

    @staticmethod
    def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        input_rate, output_rate = _PRICING.get(model, (3.0, 15.0))
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_router: ModelRouter | None = None


def get_model_router(config: dict | None = None) -> ModelRouter:
    """Return the process-wide ModelRouter singleton."""
    global _router
    if _router is None:
        _router = ModelRouter(config)
    return _router
