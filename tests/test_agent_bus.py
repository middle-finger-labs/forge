"""Tests for agent-to-agent communication bus.

All tests mock ModelRouter and stream_agent_log — no real API or Redis calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.communication.agent_bus import AgentBus
from agents.communication.briefing import get_architect_briefing, get_qa_clarification
from agents.communication.types import AgentResponse
from contracts.schemas import AgentRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_router(content: str = "Mock answer", cost: float = 0.01):
    """Return a mock ModelRouter with preset complete() response."""
    router = MagicMock()
    router.route_request = AsyncMock(return_value="claude-sonnet-4-5")
    router.complete = AsyncMock(return_value={
        "content": content,
        "model_used": "claude-sonnet-4-5",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": cost,
        "latency_ms": 200,
    })
    return router


def _patch_deps(router=None):
    """Patch ModelRouter and stream_agent_log.

    Both are lazily imported inside methods, so we patch at the source
    module and use ``create=True`` isn't needed — we patch the source.
    """
    if router is None:
        router = _mock_router()
    return (
        patch("config.model_router.get_model_router", return_value=router),
        patch("memory.agent_log.stream_agent_log", new_callable=AsyncMock),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_returns_response():
    """Mock router.complete() -> verify response text and cost returned."""
    router = _mock_router(content="Use the repository pattern.", cost=0.02)
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-1")
        resp = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "What pattern?")

    assert isinstance(resp, AgentResponse)
    assert resp.response == "Use the repository pattern."
    assert resp.cost_usd == 0.02
    assert resp.from_role == AgentRole.DEVELOPER
    assert resp.to_role == AgentRole.ARCHITECT
    assert not resp.timed_out
    assert not resp.hit_limit
    assert not resp.circular


@pytest.mark.asyncio
async def test_ask_question_limit_enforced():
    """4 calls with max=3 -> 4th returns limit message, no LLM call."""
    router = _mock_router()
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-2", max_questions_per_agent=3)

        for _ in range(3):
            resp = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q?")
            assert not resp.hit_limit

        resp = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q4?")
        assert resp.hit_limit
        assert "limit reached" in resp.response.lower()

    # Router should have been called exactly 3 times (not 4)
    assert router.complete.call_count == 3


@pytest.mark.asyncio
async def test_ask_circular_detection():
    """A->B then B->A -> second returns 'resolve independently'."""
    router = _mock_router()

    async def slow_complete(*args, **kwargs):
        await asyncio.sleep(0.5)
        return {
            "content": "Slow answer",
            "cost_usd": 0.01,
        }

    router.complete = AsyncMock(side_effect=slow_complete)
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-3")

        async def ask_a_to_b():
            return await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q from dev?")

        async def ask_b_to_a():
            # Small delay to ensure A->B is active first
            await asyncio.sleep(0.05)
            return await bus.ask(AgentRole.ARCHITECT, AgentRole.DEVELOPER, "Q from arch?")

        resp_ab, resp_ba = await asyncio.gather(ask_a_to_b(), ask_b_to_a())

    # The first ask should succeed
    assert not resp_ab.circular
    # The second ask should detect the circular dependency
    assert resp_ba.circular
    assert "circular" in resp_ba.response.lower()


@pytest.mark.asyncio
async def test_ask_timeout_returns_fallback():
    """Router raises TimeoutError -> graceful fallback message."""
    router = _mock_router()

    async def timeout_complete(*args, **kwargs):
        await asyncio.sleep(10)

    router.complete = AsyncMock(side_effect=timeout_complete)
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-4", question_timeout=0.1)
        resp = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Hello?")

    assert resp.timed_out
    assert "unable to reach" in resp.response.lower()
    assert resp.cost_usd == 0.0


@pytest.mark.asyncio
async def test_ask_tracks_cost():
    """2 calls with known costs -> total_cost_usd equals sum."""
    router = _mock_router()
    call_count = 0

    async def varying_cost(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "content": f"Answer {call_count}",
            "cost_usd": 0.01 * call_count,
        }

    router.complete = AsyncMock(side_effect=varying_cost)
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-5")
        await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q1?")
        await bus.ask(AgentRole.QA_ENGINEER, AgentRole.DEVELOPER, "Q2?")

    assert bus.total_cost_usd == pytest.approx(0.03)  # 0.01 + 0.02


@pytest.mark.asyncio
async def test_broadcast_no_llm_call():
    """Mock stream_agent_log -> verify event emitted, no LLM call."""
    router = _mock_router()
    p_router, p_log = _patch_deps(router)

    with p_router, p_log as mock_log:
        bus = AgentBus("pipe-6")
        await bus.broadcast(AgentRole.CTO, "Pipeline is healthy")

    # No LLM call should have been made
    router.complete.assert_not_called()
    router.route_request.assert_not_called()

    # stream_agent_log should have been called
    mock_log.assert_called_once()
    call_args = mock_log.call_args
    assert call_args[0][1] == "agent_bus.broadcast"


@pytest.mark.asyncio
async def test_exchanges_logged():
    """Make 2 asks -> exchanges property returns both."""
    router = _mock_router()
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-7")
        await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q1?")
        await bus.ask(AgentRole.QA_ENGINEER, AgentRole.DEVELOPER, "Q2?")

    exchanges = bus.exchanges
    assert len(exchanges) == 2
    assert exchanges[0]["from_role"] == AgentRole.DEVELOPER
    assert exchanges[0]["to_role"] == AgentRole.ARCHITECT
    assert exchanges[1]["from_role"] == AgentRole.QA_ENGINEER
    assert exchanges[1]["to_role"] == AgentRole.DEVELOPER

    # Verify it returns a copy
    bus.exchanges.append({"fake": True})
    assert len(bus.exchanges) == 2


@pytest.mark.asyncio
async def test_get_architect_briefing_formats_correctly():
    """Mock bus -> verify <architect_briefing> tags."""
    bus = MagicMock(spec=AgentBus)
    bus.ask = AsyncMock(return_value=AgentResponse(
        from_role=AgentRole.DEVELOPER,
        to_role=AgentRole.ARCHITECT,
        question="What patterns?",
        response="Use repository pattern with dependency injection.",
        cost_usd=0.01,
    ))

    ticket = {
        "ticket_key": "FORGE-1",
        "title": "Add user auth",
        "files_owned": ["src/auth.py"],
        "acceptance_criteria": ["Users can log in"],
    }

    result = await get_architect_briefing(bus, ticket, "tech spec context")

    assert result.startswith("<architect_briefing>")
    assert result.endswith("</architect_briefing>")
    assert "repository pattern" in result
    bus.ask.assert_called_once()


@pytest.mark.asyncio
async def test_get_qa_clarification_formats_correctly():
    """Mock bus -> verify <engineer_clarification> tags."""
    bus = MagicMock(spec=AgentBus)
    bus.ask = AsyncMock(return_value=AgentResponse(
        from_role=AgentRole.QA_ENGINEER,
        to_role=AgentRole.DEVELOPER,
        question="Why no validation?",
        response="Validation is handled by the middleware layer.",
        cost_usd=0.01,
    ))

    ticket = {"ticket_key": "FORGE-2"}
    qa_review = {
        "revision_instructions": ["Add input validation to endpoint"],
        "comments": [
            {"severity": "error", "comment": "Missing validation"},
        ],
    }
    code_artifact = {
        "files_created": ["src/api.py"],
        "files_modified": [],
        "notes": "Used middleware pattern",
    }

    result = await get_qa_clarification(bus, ticket, qa_review, code_artifact)

    assert result.startswith("<engineer_clarification>")
    assert result.endswith("</engineer_clarification>")
    assert "middleware" in result
    bus.ask.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_asks_dont_interfere():
    """Two parallel asks to different agents -> both succeed."""
    router = _mock_router()
    call_count = 0

    async def sequential_answers(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        n = call_count
        await asyncio.sleep(0.05)
        return {
            "content": f"Answer {n}",
            "cost_usd": 0.01,
        }

    router.complete = AsyncMock(side_effect=sequential_answers)
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-8")

        r1, r2 = await asyncio.gather(
            bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q from dev?"),
            bus.ask(AgentRole.QA_ENGINEER, AgentRole.CTO, "Q from QA?"),
        )

    assert not r1.timed_out and not r1.hit_limit
    assert not r2.timed_out and not r2.hit_limit
    assert r1.response.startswith("Answer")
    assert r2.response.startswith("Answer")
    assert bus.total_cost_usd == pytest.approx(0.02)
    assert len(bus.exchanges) == 2


# ---------------------------------------------------------------------------
# Inter-agent messages visible in pipeline conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchanges_contain_question_and_response():
    """Each exchange entry records both the question and the response text."""
    router = _mock_router(content="Use hexagonal architecture.")
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-9")
        await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "What pattern?")

    exchanges = bus.exchanges
    assert len(exchanges) == 1
    ex = exchanges[0]
    assert ex["question"] == "What pattern?"
    assert ex["response"] == "Use hexagonal architecture."
    assert ex["from_role"] == AgentRole.DEVELOPER
    assert ex["to_role"] == AgentRole.ARCHITECT
    assert "timestamp" in ex


@pytest.mark.asyncio
async def test_exchanges_include_limit_hit_entries():
    """When question limit is hit, the exchange is still recorded."""
    router = _mock_router()
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-10", max_questions_per_agent=1)
        await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q1?")
        await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Q2 (should be limited)?")

    exchanges = bus.exchanges
    assert len(exchanges) == 2
    assert not exchanges[0].get("hit_limit", False)
    # Second exchange is the limit-hit entry
    assert exchanges[1].get("hit_limit", False) or "limit" in exchanges[1]["response"].lower()


@pytest.mark.asyncio
async def test_exchanges_include_timeout_entries():
    """When a request times out, the exchange is still recorded."""
    router = _mock_router()

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    router.complete = AsyncMock(side_effect=slow)
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-11", question_timeout=0.1)
        await bus.ask(AgentRole.QA_ENGINEER, AgentRole.DEVELOPER, "Review?")

    exchanges = bus.exchanges
    assert len(exchanges) == 1
    assert exchanges[0].get("timed_out", False) or "unable" in exchanges[0]["response"].lower()


@pytest.mark.asyncio
async def test_multiple_agents_tracked_separately():
    """Question limits apply per from_role, not globally."""
    router = _mock_router()
    p_router, p_log = _patch_deps(router)

    with p_router, p_log:
        bus = AgentBus("pipe-12", max_questions_per_agent=2)

        # Developer asks 2 questions (at limit)
        r1 = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Dev Q1?")
        r2 = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Dev Q2?")
        assert not r1.hit_limit
        assert not r2.hit_limit

        # QA can still ask (separate counter)
        r3 = await bus.ask(AgentRole.QA_ENGINEER, AgentRole.ARCHITECT, "QA Q1?")
        assert not r3.hit_limit

        # Developer is now limited
        r4 = await bus.ask(AgentRole.DEVELOPER, AgentRole.ARCHITECT, "Dev Q3?")
        assert r4.hit_limit

    assert len(bus.exchanges) == 4


@pytest.mark.asyncio
async def test_broadcast_recorded_in_log():
    """Broadcast events are logged via stream_agent_log with correct data."""
    router = _mock_router()
    p_router, p_log = _patch_deps(router)

    with p_router, p_log as mock_log:
        bus = AgentBus("pipe-13")
        await bus.broadcast(AgentRole.ARCHITECT, "Architecture review complete")

    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args[1] if mock_log.call_args[1] else {}
    call_args = mock_log.call_args[0]
    # First positional arg is pipeline_id
    assert call_args[0] == "pipe-13"
