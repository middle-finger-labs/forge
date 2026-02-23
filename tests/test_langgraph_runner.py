"""Unit tests for the LangGraph runner.

Tests the graph structure, validation retry loop, retry exhaustion,
and cost tracking — all without making real API calls.

Mocks the ModelRouter to avoid any network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agents.langgraph_runner import build_agent_graph, run_agent

# ---------------------------------------------------------------------------
# Test output model
# ---------------------------------------------------------------------------


class SimpleOutput(BaseModel):
    name: str
    value: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JSON = '{"name": "test", "value": 42}'
INVALID_JSON = '{"name": "test"}'  # missing required field "value"

INPUT_TOKENS = 100
OUTPUT_TOKENS = 50


def _expected_cost_per_call() -> float:
    """Cost for one LLM call using default Sonnet 4.5 pricing (3.0 / 15.0 per 1M)."""
    return (INPUT_TOKENS * 3.0 + OUTPUT_TOKENS * 15.0) / 1_000_000


def _make_router_response(content: str) -> dict:
    """Build a mock ModelRouter.complete() return value."""
    return {
        "content": content,
        "model_used": "claude-sonnet-4-5-20250929",
        "input_tokens": INPUT_TOKENS,
        "output_tokens": OUTPUT_TOKENS,
        "cost_usd": _expected_cost_per_call(),
        "latency_ms": 50.0,
    }


def _mock_router(*responses: dict) -> MagicMock:
    """Return a mock ModelRouter whose complete() yields *responses* in order.

    If only one response is given, it repeats for every call.
    """
    router = MagicMock()
    router.route_request = AsyncMock(return_value="claude-sonnet-4-5-20250929")

    if len(responses) == 1:
        router.complete = AsyncMock(return_value=responses[0])
    else:
        router.complete = AsyncMock(side_effect=list(responses))

    return router


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildAgentGraph:
    """build_agent_graph returns a compiled graph with the expected nodes."""

    def test_graph_has_correct_nodes(self) -> None:
        graph = build_agent_graph("system prompt", SimpleOutput)

        node_names = sorted(graph.get_graph().nodes)
        assert node_names == ["__end__", "__start__", "call_llm", "validate_output"]


class TestValidationRetryLoop:
    """LLM returns invalid JSON first, valid JSON second -- graph retries."""

    @pytest.mark.asyncio
    async def test_retry_produces_valid_output(self) -> None:
        router = _mock_router(
            _make_router_response(INVALID_JSON),
            _make_router_response(VALID_JSON),
        )

        with patch("config.model_router.get_model_router", return_value=router):
            result, cost = await run_agent(
                system_prompt="You are a test agent.",
                human_prompt="Give me output.",
                output_model=SimpleOutput,
                max_retries=3,
            )

        # The valid output should be captured after the retry.
        assert result is not None
        assert result["name"] == "test"
        assert result["value"] == 42

        # The router was called exactly twice (first invalid, then valid).
        assert router.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_remaining_decrements(self) -> None:
        """Verify that retries_remaining drops by 1 for each validation failure."""
        router = _mock_router(
            _make_router_response(INVALID_JSON),
            _make_router_response(VALID_JSON),
        )

        with patch("config.model_router.get_model_router", return_value=router):
            graph = build_agent_graph(
                "You are a test agent.",
                SimpleOutput,
                max_retries=3,
            )

            initial_state = {
                "messages": [{"role": "user", "content": "Give me output."}],
                "output_json": None,
                "retries_remaining": 3,
                "validation_errors": [],
                "stage_name": "",
                "cost_usd": 0.0,
            }

            final_state = await graph.ainvoke(initial_state)

        # One validation failure means retries went from 3 to 2.
        assert final_state["retries_remaining"] == 2
        assert final_state["output_json"] is not None


class TestRetriesExhausted:
    """When the LLM never returns valid output, the graph gives up."""

    @pytest.mark.asyncio
    async def test_exhausted_retries_returns_none(self) -> None:
        router = _mock_router(_make_router_response(INVALID_JSON))

        with patch("config.model_router.get_model_router", return_value=router):
            result, cost = await run_agent(
                system_prompt="You are a test agent.",
                human_prompt="Give me output.",
                output_model=SimpleOutput,
                max_retries=2,
            )

        # Output should be None because retries were exhausted.
        assert result is None

        # max_retries=2 means the graph loops exactly twice before giving up.
        assert router.complete.call_count == 2


class TestCostTracking:
    """Cost accumulates correctly across LLM calls."""

    @pytest.mark.asyncio
    async def test_cost_accumulates_on_single_call(self) -> None:
        router = _mock_router(_make_router_response(VALID_JSON))

        with patch("config.model_router.get_model_router", return_value=router):
            _, cost = await run_agent(
                system_prompt="You are a test agent.",
                human_prompt="Give me output.",
                output_model=SimpleOutput,
            )

        expected = _expected_cost_per_call()
        assert cost == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_cost_accumulates_across_retries(self) -> None:
        router = _mock_router(
            _make_router_response(INVALID_JSON),
            _make_router_response(VALID_JSON),
        )

        with patch("config.model_router.get_model_router", return_value=router):
            _, cost = await run_agent(
                system_prompt="You are a test agent.",
                human_prompt="Give me output.",
                output_model=SimpleOutput,
                max_retries=3,
            )

        # Two LLM calls total, so cost should be double one call.
        expected = _expected_cost_per_call() * 2
        assert cost == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_cost_accumulates_when_retries_exhausted(self) -> None:
        router = _mock_router(_make_router_response(INVALID_JSON))

        with patch("config.model_router.get_model_router", return_value=router):
            _, cost = await run_agent(
                system_prompt="You are a test agent.",
                human_prompt="Give me output.",
                output_model=SimpleOutput,
                max_retries=3,
            )

        # max_retries=3 means 3 LLM calls before giving up.
        expected = _expected_cost_per_call() * 3
        assert cost == pytest.approx(expected)


class TestAgentRoleRouting:
    """When agent_role is provided, ModelRouter.route_request selects the model."""

    @pytest.mark.asyncio
    async def test_agent_role_triggers_routing(self) -> None:
        router = _mock_router(_make_router_response(VALID_JSON))

        with patch("config.model_router.get_model_router", return_value=router):
            result, _ = await run_agent(
                system_prompt="You are a test agent.",
                human_prompt="Give me output.",
                output_model=SimpleOutput,
                agent_role="architect",
            )

        assert result is not None
        # route_request should be called twice — once in run_agent, once in call_llm
        assert router.route_request.call_count >= 1
        router.route_request.assert_any_call("architect")
