"""Unit tests for the Forge error hierarchy and ErrorReporter.

Tests cover:
  - ForgeError subclass defaults (is_retryable, required fields)
  - to_dict() serialization round-trip
  - _classify_and_wrap: each error category
  - ErrorReporter sliding-window circuit breaker
  - ErrorReporter.report() with mocked PG/Redis
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from config.errors import (
    AgentTimeoutError,
    BudgetExceededError,
    ContentPolicyError,
    ErrorReporter,
    ForgeError,
    GitError,
    LLMError,
    MergeConflictError,
    ValidationError,
    get_error_reporter,
)

# ---------------------------------------------------------------------------
# Retryability defaults
# ---------------------------------------------------------------------------


class TestRetryabilityDefaults:
    def test_forge_error_retryable(self):
        e = ForgeError("base error")
        assert e.is_retryable is True

    def test_llm_error_retryable(self):
        e = LLMError("model failed")
        assert e.is_retryable is True

    def test_content_policy_not_retryable(self):
        e = ContentPolicyError("blocked by policy")
        assert e.is_retryable is False

    def test_validation_not_retryable(self):
        e = ValidationError("bad output")
        assert e.is_retryable is False

    def test_budget_exceeded_not_retryable(self):
        e = BudgetExceededError("over budget")
        assert e.is_retryable is False

    def test_git_error_retryable(self):
        e = GitError("git failed")
        assert e.is_retryable is True

    def test_merge_conflict_retryable(self):
        e = MergeConflictError("conflict in main.py")
        assert e.is_retryable is True

    def test_agent_timeout_retryable(self):
        e = AgentTimeoutError("timed out")
        assert e.is_retryable is True

    def test_override_retryable(self):
        e = LLMError("model failed", is_retryable=False)
        assert e.is_retryable is False


# ---------------------------------------------------------------------------
# to_dict() serialization
# ---------------------------------------------------------------------------


class TestToDict:
    def test_base_error_to_dict(self):
        e = ForgeError(
            "something broke",
            pipeline_id="pipe-1",
            stage="coding",
            agent_role="engineer",
        )
        d = e.to_dict()
        assert d["error_type"] == "ForgeError"
        assert d["message"] == "something broke"
        assert d["pipeline_id"] == "pipe-1"
        assert d["stage"] == "coding"
        assert d["agent_role"] == "engineer"
        assert d["is_retryable"] is True
        assert isinstance(d["context"], dict)

    def test_llm_error_to_dict(self):
        e = LLMError("rate limited", model="claude-3", error_category="rate_limit")
        d = e.to_dict()
        assert d["error_type"] == "LLMError"
        assert d["model"] == "claude-3"
        assert d["error_category"] == "rate_limit"

    def test_content_policy_to_dict(self):
        e = ContentPolicyError("blocked")
        d = e.to_dict()
        assert d["error_type"] == "ContentPolicyError"
        assert d["error_category"] == "content_policy"
        assert d["is_retryable"] is False

    def test_validation_error_to_dict(self):
        e = ValidationError(
            "bad schema",
            validation_errors=["field 'x' missing", "field 'y' wrong type"],
        )
        d = e.to_dict()
        assert d["error_type"] == "ValidationError"
        assert len(d["validation_errors"]) == 2
        assert "field 'x' missing" in d["validation_errors"]

    def test_budget_exceeded_to_dict(self):
        e = BudgetExceededError("over", current_cost=45.0, max_cost=50.0)
        d = e.to_dict()
        assert d["error_type"] == "BudgetExceededError"
        assert d["current_cost"] == 45.0
        assert d["max_cost"] == 50.0

    def test_merge_conflict_to_dict(self):
        e = MergeConflictError("conflict", conflicting_files=["a.py", "b.py"])
        d = e.to_dict()
        assert d["error_type"] == "MergeConflictError"
        assert d["conflicting_files"] == ["a.py", "b.py"]

    def test_agent_timeout_to_dict(self):
        e = AgentTimeoutError("slow", timeout_seconds=300.0)
        d = e.to_dict()
        assert d["error_type"] == "AgentTimeoutError"
        assert d["timeout_seconds"] == 300.0

    def test_to_dict_json_serializable(self):
        """All to_dict() outputs must be JSON-serializable."""
        errors = [
            ForgeError("msg", pipeline_id="p", stage="s", agent_role="a"),
            LLMError("msg", model="m", error_category="rate_limit"),
            ContentPolicyError("msg"),
            ValidationError("msg", validation_errors=["e1"]),
            BudgetExceededError("msg", current_cost=1.0, max_cost=2.0),
            GitError("msg"),
            MergeConflictError("msg", conflicting_files=["f.py"]),
            AgentTimeoutError("msg", timeout_seconds=60.0),
        ]
        for err in errors:
            d = err.to_dict()
            # Must not raise
            serialized = json.dumps(d)
            assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# _classify_and_wrap
# ---------------------------------------------------------------------------


class TestClassifyAndWrap:
    """Test the error classification helper from pipeline_activities."""

    @pytest.fixture(autouse=True)
    def _import_classify(self):
        from activities.pipeline_activities import _classify_and_wrap

        self.classify = _classify_and_wrap

    def _wrap(self, exc):
        return self.classify(
            exc,
            pipeline_id="test-pipe",
            stage="test-stage",
            agent_role="tester",
        )

    def test_timeout_error(self):
        result = self._wrap(TimeoutError("operation timed out"))
        assert isinstance(result, AgentTimeoutError)

    def test_budget_exceeded(self):
        result = self._wrap(RuntimeError("Budget exceeded: $50.00 / $50.00"))
        assert isinstance(result, BudgetExceededError)

    def test_budget_limit(self):
        result = self._wrap(RuntimeError("Cost budget limit reached"))
        assert isinstance(result, BudgetExceededError)

    def test_content_policy(self):
        result = self._wrap(RuntimeError("Request blocked by content policy"))
        assert isinstance(result, ContentPolicyError)
        assert result.is_retryable is False

    def test_content_filter(self):
        result = self._wrap(RuntimeError("content filter triggered"))
        assert isinstance(result, ContentPolicyError)

    def test_worktree_error_by_name(self):
        # Simulate WorktreeError by creating a class with that name
        class WorktreeError(Exception):
            pass

        result = self._wrap(WorktreeError("git worktree add failed"))
        assert isinstance(result, GitError)

    def test_worktree_merge_conflict(self):
        result = self._wrap(RuntimeError("worktree merge conflict in main.py"))
        assert isinstance(result, MergeConflictError)

    def test_rate_limit_429(self):
        result = self._wrap(RuntimeError("Error 429: rate limit exceeded"))
        assert isinstance(result, LLMError)
        assert result.error_category == "rate_limit"

    def test_rate_limit_text(self):
        result = self._wrap(RuntimeError("rate_limit error from API"))
        assert isinstance(result, LLMError)
        assert result.error_category == "rate_limit"

    def test_server_error_500(self):
        result = self._wrap(RuntimeError("Internal Server Error 500"))
        assert isinstance(result, LLMError)
        assert result.error_category == "server_error"

    def test_server_error_503(self):
        result = self._wrap(RuntimeError("Service Unavailable 503"))
        assert isinstance(result, LLMError)
        assert result.error_category == "server_error"

    def test_validation_error(self):
        result = self._wrap(ValueError("validation failed for field X"))
        assert isinstance(result, ValidationError)
        assert len(result.validation_errors) == 1

    def test_unknown_fallback(self):
        result = self._wrap(RuntimeError("something unexpected"))
        assert isinstance(result, LLMError)
        assert result.error_category == "unknown"

    def test_preserves_context(self):
        result = self._wrap(RuntimeError("any error"))
        assert result.pipeline_id == "test-pipe"
        assert result.stage == "test-stage"
        assert result.agent_role == "tester"


# ---------------------------------------------------------------------------
# ErrorReporter: circuit breaker
# ---------------------------------------------------------------------------


class TestErrorReporterCircuitBreaker:
    def test_initial_frequency_zero(self):
        reporter = ErrorReporter()
        assert reporter.get_error_frequency("coding") == 0

    def test_should_not_circuit_break_below_threshold(self):
        reporter = ErrorReporter()
        assert reporter.should_circuit_break("coding", threshold=5) is False

    def test_frequency_increases(self):
        reporter = ErrorReporter(window_seconds=300.0)
        # Manually add timestamps
        reporter._error_counts["coding"] = __import__("collections").deque()
        now = time.monotonic()
        for _ in range(3):
            reporter._error_counts["coding"].append(now)
        assert reporter.get_error_frequency("coding") == 3

    def test_circuit_breaks_at_threshold(self):
        reporter = ErrorReporter(window_seconds=300.0)
        from collections import deque

        now = time.monotonic()
        reporter._error_counts["coding"] = deque([now] * 5)
        assert reporter.should_circuit_break("coding", threshold=5) is True

    def test_expired_entries_evicted(self):
        reporter = ErrorReporter(window_seconds=10.0)
        from collections import deque

        now = time.monotonic()
        # All entries are 20 seconds old → outside the 10s window
        reporter._error_counts["coding"] = deque([now - 20] * 5)
        assert reporter.get_error_frequency("coding") == 0
        assert reporter.should_circuit_break("coding", threshold=5) is False

    def test_mixed_fresh_and_expired(self):
        reporter = ErrorReporter(window_seconds=10.0)
        from collections import deque

        now = time.monotonic()
        # 3 expired + 2 fresh
        reporter._error_counts["coding"] = deque([now - 20, now - 15, now - 11, now - 1, now])
        assert reporter.get_error_frequency("coding") == 2


# ---------------------------------------------------------------------------
# ErrorReporter.report() — best-effort persistence
# ---------------------------------------------------------------------------


class TestErrorReporterReport:
    @pytest.mark.asyncio
    async def test_report_logs_and_tracks(self):
        reporter = ErrorReporter()
        error = LLMError(
            "model crashed",
            pipeline_id="pipe-1",
            stage="coding",
            agent_role="engineer",
        )

        # report() uses lazy imports with try/except — PG and Redis
        # will fail gracefully in test env, but the sliding window
        # should still be updated.
        await reporter.report(error)

        assert reporter.get_error_frequency("coding") == 1

    @pytest.mark.asyncio
    async def test_report_survives_pg_failure(self):
        reporter = ErrorReporter()
        error = GitError("git broke", pipeline_id="p", stage="merge")

        # All persistence is best-effort; should not raise even
        # without PG/Redis running.
        await reporter.report(error)

        assert reporter.get_error_frequency("merge") == 1

    @pytest.mark.asyncio
    async def test_report_calls_pg_and_redis(self):
        reporter = ErrorReporter()
        error = ValidationError("bad output", pipeline_id="p", stage="ba")

        mock_store = AsyncMock()
        mock_wm = AsyncMock()

        # Patch the lazy imports at the module level in sys.modules
        mock_memory = type(
            "MockMemory",
            (),
            {
                "get_state_store": staticmethod(lambda: mock_store),
                "get_working_memory": staticmethod(lambda: mock_wm),
            },
        )()

        with patch.dict("sys.modules", {"memory": mock_memory}):
            await reporter.report(error)

        mock_store.record_event.assert_called_once()
        mock_wm.emit_event.assert_called_once()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_error_reporter_returns_same_instance(self):
        r1 = get_error_reporter()
        r2 = get_error_reporter()
        assert r1 is r2
