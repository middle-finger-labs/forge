"""Typed exception hierarchy for the Forge pipeline.

Pure-Python exception classes (no heavy imports) — safe for Temporal sandbox
import.  Each exception carries structured context so the workflow can make
intelligent retry decisions per error type.

Hierarchy::

    ForgeError(Exception)
    +-- LLMError                 is_retryable=True
    |   +-- ContentPolicyError   is_retryable=False
    +-- ValidationError          is_retryable=False
    +-- BudgetExceededError      is_retryable=False
    +-- GitError                 is_retryable=True
    |   +-- MergeConflictError   is_retryable=True
    +-- AgentTimeoutError        is_retryable=True
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class ForgeError(Exception):
    """Base class for all typed Forge pipeline errors."""

    is_retryable: bool = True

    def __init__(
        self,
        message: str,
        *,
        pipeline_id: str = "",
        stage: str = "",
        agent_role: str = "",
        is_retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.pipeline_id = pipeline_id
        self.stage = stage
        self.agent_role = agent_role
        if is_retryable is not None:
            self.is_retryable = is_retryable
        self.context: dict[str, Any] = context or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for Temporal ApplicationError details."""
        return {
            "error_type": type(self).__name__,
            "message": str(self),
            "pipeline_id": self.pipeline_id,
            "stage": self.stage,
            "agent_role": self.agent_role,
            "is_retryable": self.is_retryable,
            "context": self.context,
        }


# ---------------------------------------------------------------------------
# LLM errors
# ---------------------------------------------------------------------------


class LLMError(ForgeError):
    """An LLM API call failed (rate limit, server error, timeout, etc.)."""

    is_retryable = True

    def __init__(
        self,
        message: str,
        *,
        model: str = "",
        error_category: str = "unknown",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.model = model
        self.error_category = error_category

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d = super().to_dict()
        d["model"] = self.model
        d["error_category"] = self.error_category
        return d


class ContentPolicyError(LLMError):
    """Request was blocked by the LLM provider's content policy."""

    is_retryable = False

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_category", "content_policy")
        super().__init__(message, **kwargs)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class ValidationError(ForgeError):
    """Agent output failed validation (schema, quality gate, etc.)."""

    is_retryable = False

    def __init__(
        self,
        message: str,
        *,
        validation_errors: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.validation_errors: list[str] = validation_errors or []

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d = super().to_dict()
        d["validation_errors"] = self.validation_errors
        return d


# ---------------------------------------------------------------------------
# Budget errors
# ---------------------------------------------------------------------------


class BudgetExceededError(ForgeError):
    """Pipeline has exceeded its cost budget."""

    is_retryable = False

    def __init__(
        self,
        message: str,
        *,
        current_cost: float = 0.0,
        max_cost: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.current_cost = current_cost
        self.max_cost = max_cost

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d = super().to_dict()
        d["current_cost"] = self.current_cost
        d["max_cost"] = self.max_cost
        return d


# ---------------------------------------------------------------------------
# Git errors
# ---------------------------------------------------------------------------


class GitError(ForgeError):
    """A git operation failed."""

    is_retryable = True


class MergeConflictError(GitError):
    """A git merge produced conflicts."""

    is_retryable = True

    def __init__(
        self,
        message: str,
        *,
        conflicting_files: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.conflicting_files: list[str] = conflicting_files or []

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d = super().to_dict()
        d["conflicting_files"] = self.conflicting_files
        return d


# ---------------------------------------------------------------------------
# Timeout errors
# ---------------------------------------------------------------------------


class AgentTimeoutError(ForgeError):
    """An agent exceeded its time budget."""

    is_retryable = True

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.timeout_seconds = timeout_seconds

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d = super().to_dict()
        d["timeout_seconds"] = self.timeout_seconds
        return d


# ---------------------------------------------------------------------------
# ErrorReporter — sliding-window error tracking + best-effort persistence
# ---------------------------------------------------------------------------


class ErrorReporter:
    """Track error frequency per stage and report errors to PG/Redis.

    All persistence operations are best-effort — failures are logged but
    never raise.
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        self._window_seconds = window_seconds
        self._error_counts: dict[str, deque[float]] = {}

    async def report(self, error: ForgeError) -> None:
        """Log the error, record in PG, emit to Redis — all best-effort."""
        # Track in sliding window
        stage = error.stage or "unknown"
        now = time.monotonic()
        if stage not in self._error_counts:
            self._error_counts[stage] = deque()
        self._error_counts[stage].append(now)

        # Structlog
        try:
            import structlog

            logger = structlog.get_logger()
            logger.error(
                "forge_error",
                error_type=type(error).__name__,
                message=str(error),
                pipeline_id=error.pipeline_id,
                stage=error.stage,
                agent_role=error.agent_role,
                is_retryable=error.is_retryable,
            )
        except Exception:
            pass

        # PostgreSQL (lazy import to avoid sandbox issues)
        try:
            from memory import get_state_store

            store = get_state_store()
            await store.record_event(
                pipeline_id=error.pipeline_id,
                agent_role=error.agent_role or "",
                event_type=f"error.{type(error).__name__}",
                payload=error.to_dict(),
            )
        except Exception:
            pass

        # Redis pub/sub
        try:
            from memory import get_working_memory

            wm = get_working_memory()
            await wm.emit_event(error.pipeline_id, error.to_dict())
        except Exception:
            pass

    def get_error_frequency(self, stage: str) -> int:
        """Count errors in the sliding window for *stage*."""
        if stage not in self._error_counts:
            return 0
        now = time.monotonic()
        dq = self._error_counts[stage]
        cutoff = now - self._window_seconds
        # Evict expired entries
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq)

    def should_circuit_break(self, stage: str, threshold: int = 5) -> bool:
        """Return True if the error frequency for *stage* exceeds *threshold*."""
        return self.get_error_frequency(stage) >= threshold

    async def get_error_summary(self, pipeline_id: str) -> dict[str, Any]:
        """Query PG for error events grouped by type (best-effort)."""
        try:
            from memory import get_state_store

            store = get_state_store()
            events = await store.get_events(
                pipeline_id,
                event_type_prefix="error.",
            )
            summary: dict[str, int] = {}
            for evt in events:
                etype = evt.get("event_type", "unknown")
                summary[etype] = summary.get(etype, 0) + 1
            return {"pipeline_id": pipeline_id, "error_counts": summary}
        except Exception:
            return {"pipeline_id": pipeline_id, "error_counts": {}}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_reporter: ErrorReporter | None = None


def get_error_reporter() -> ErrorReporter:
    """Return the module-level ErrorReporter singleton."""
    global _reporter  # noqa: PLW0603
    if _reporter is None:
        _reporter = ErrorReporter()
    return _reporter
