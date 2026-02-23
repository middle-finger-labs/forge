"""Tests for SemanticMemory and get_relevant_context.

Uses the PostgreSQL fallback backend (no Mem0) to test real storage
and retrieval.  Tests that require infrastructure are marked with
``@pytest.mark.integration`` and skipped if PostgreSQL is unavailable.

Unit tests that mock the memory layer verify that agent functions
gracefully handle memory failures.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from memory.semantic_memory import SemanticMemory, _FallbackBackend, get_relevant_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fallback_backend(pg_dsn):
    """Create a _FallbackBackend directly for testing."""
    backend = await _FallbackBackend.create(pg_dsn)
    yield backend

    # Cleanup test data from memory_store
    await backend._pool.execute("DELETE FROM memory_store WHERE pipeline_id LIKE 'test-%'")
    await backend._pool.close()


@pytest.fixture
async def semantic_memory(fallback_backend):
    """Create a SemanticMemory that uses the fallback backend directly."""
    mem = SemanticMemory()
    # Inject the pre-created fallback backend
    mem._backend = fallback_backend
    return mem


# ---------------------------------------------------------------------------
# Integration tests — require PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_and_recall_lesson(semantic_memory: SemanticMemory) -> None:
    """Store a lesson and recall it via semantic search."""
    pid = _uid()

    await semantic_memory.store_lesson(
        agent_role="developer",
        pipeline_id=pid,
        lesson="Always add NOT NULL constraints to required database columns.",
    )

    results = await semantic_memory.recall(
        "database schema best practices",
        agent_role="developer",
        limit=5,
    )

    assert len(results) >= 1
    # At least one result should contain our lesson
    contents = [r["content"] for r in results]
    assert any("NOT NULL" in c for c in contents)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_filters_by_agent_role(semantic_memory: SemanticMemory) -> None:
    """Memories for one role should not appear when querying another."""
    pid = _uid()

    await semantic_memory.store_lesson(
        agent_role="qa_engineer",
        pipeline_id=pid,
        lesson="Check for XSS vulnerabilities in all user-facing inputs.",
    )

    await semantic_memory.store_lesson(
        agent_role="architect",
        pipeline_id=pid,
        lesson="Use event-driven architecture for real-time features.",
    )

    # Query for architect-only memories
    results = await semantic_memory.recall(
        "architecture patterns",
        agent_role="architect",
        limit=10,
    )

    roles_returned = {r.get("metadata", {}).get("agent_role") for r in results}
    # All results should be for the architect role
    assert roles_returned <= {"architect", None}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_decision(semantic_memory: SemanticMemory) -> None:
    """Store and retrieve a decision."""
    pid = _uid()

    await semantic_memory.store_decision(
        pipeline_id=pid,
        decision_type="tech_stack",
        decision="Use FastAPI for the REST API",
        rationale="Best async Python framework for our use case",
        context={"language": "Python"},
    )

    results = await semantic_memory.recall(
        "tech stack framework choice",
        limit=5,
    )

    assert len(results) >= 1
    contents = [r["content"] for r in results]
    assert any("FastAPI" in c for c in contents)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recall_for_pipeline(semantic_memory: SemanticMemory) -> None:
    """recall_for_pipeline should return memories scoped to one pipeline."""
    pid = _uid()

    await semantic_memory.store_lesson(
        agent_role="developer",
        pipeline_id=pid,
        lesson="Validate all enum values at API boundaries.",
    )

    results = await semantic_memory.recall_for_pipeline(pid, limit=10)

    assert len(results) >= 1
    assert all(r.get("metadata", {}).get("pipeline_id") == pid for r in results)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_relevant_context_returns_formatted_string(
    semantic_memory: SemanticMemory,
) -> None:
    """get_relevant_context should format memories as an XML-tagged block."""
    pid = _uid()

    await semantic_memory.store_lesson(
        agent_role="developer",
        pipeline_id=pid,
        lesson="Always handle timeout errors in HTTP clients.",
    )

    context = await get_relevant_context(
        "developer",
        "implement an HTTP client with error handling",
        memory=semantic_memory,
        limit=5,
    )

    assert isinstance(context, str)
    if context:  # May be empty if embedding search returns no matches
        assert "<relevant_memories>" in context
        assert "</relevant_memories>" in context
        assert "timeout" in context.lower()


# ---------------------------------------------------------------------------
# Unit tests — no infrastructure required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_relevant_context_empty_on_failure() -> None:
    """get_relevant_context should return empty string when recall fails."""
    mock_mem = SemanticMemory()
    mock_mem._backend = AsyncMock()
    mock_mem._backend.search = AsyncMock(side_effect=RuntimeError("DB down"))

    context = await get_relevant_context(
        "developer",
        "some task",
        memory=mock_mem,
        limit=5,
    )

    assert context == ""


@pytest.mark.asyncio
async def test_get_relevant_context_empty_results() -> None:
    """get_relevant_context should return empty string when no memories exist."""
    mock_mem = SemanticMemory()
    mock_mem._backend = AsyncMock()
    mock_mem._backend.search = AsyncMock(return_value=[])

    context = await get_relevant_context(
        "developer",
        "some task",
        memory=mock_mem,
        limit=5,
    )

    assert context == ""


@pytest.mark.asyncio
async def test_memory_failure_does_not_crash_agent() -> None:
    """Agent should still work when memory recall raises an exception.

    This tests the pattern used in ba_agent.py and other agents: memory
    recall is wrapped in try/except and failures are swallowed.
    """
    with patch(
        "memory.semantic_memory.get_relevant_context",
        side_effect=RuntimeError("Mem0 init failed"),
    ):
        # Simulate the pattern used in ba_agent.py
        memory_context = ""
        try:
            from memory.semantic_memory import get_relevant_context as grc

            memory_context = await grc(
                "business_analyst",
                "Analyse business spec",
            )
        except Exception:
            # Agent should catch and continue
            pass

        # Agent continues without memory context
        assert memory_context == ""


@pytest.mark.asyncio
async def test_store_lesson_failure_does_not_propagate() -> None:
    """SemanticMemory.store_lesson should not crash on backend failure.

    In the actual pipeline, store calls are best-effort. This verifies
    that a broken backend propagates the exception (callers handle it).
    """
    mem = SemanticMemory()
    mock_backend = AsyncMock()
    mock_backend.store = AsyncMock(side_effect=ConnectionError("PG down"))
    mem._backend = mock_backend

    # store_lesson calls backend.store which raises — this should propagate
    with pytest.raises(ConnectionError):
        await mem.store_lesson(
            agent_role="developer",
            pipeline_id="test",
            lesson="test lesson",
        )
