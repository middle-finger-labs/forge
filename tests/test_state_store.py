"""Integration tests for the StateStore PostgreSQL persistence layer.

Requires a running PostgreSQL instance with the forge_app database and
schema.  Tests are skipped automatically if PostgreSQL is not available.
"""

from __future__ import annotations

import uuid

import pytest

from memory.state_store import StateStore

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def store(pg_dsn):
    """Create a StateStore and clean up after the test."""
    s = StateStore(pg_dsn)
    pipeline_ids: list[str] = []

    class _Tracked(StateStore):
        pass

    # Wrap create_pipeline_run to track IDs for cleanup
    original_create = s.create_pipeline_run

    async def tracked_create(pid, *args, **kwargs):
        pipeline_ids.append(pid)
        return await original_create(pid, *args, **kwargs)

    s.create_pipeline_run = tracked_create  # type: ignore[assignment]

    yield s

    # Cleanup all test data
    pool = await s._get_pool()  # noqa: SLF001
    for pid in pipeline_ids:
        await pool.execute("DELETE FROM agent_events WHERE pipeline_id = $1", pid)
        await pool.execute("DELETE FROM cto_interventions WHERE pipeline_id = $1", pid)
        await pool.execute("DELETE FROM ticket_executions WHERE pipeline_id = $1", pid)
        await pool.execute("DELETE FROM pipeline_runs WHERE pipeline_id = $1", pid)
    await s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_read_pipeline(store: StateStore) -> None:
    """Create a pipeline run, then read it back and verify fields."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Build a chat app", "ChatApp")

    row = await store.get_pipeline(pid)
    assert row is not None
    assert row["pipeline_id"] == pid
    assert row["business_spec"] == "Build a chat app"
    assert row["project_name"] == "ChatApp"
    assert row["status"] == "running"
    assert row["current_stage"] == "intake"


@pytest.mark.asyncio
async def test_update_stage_persists_artifact(store: StateStore) -> None:
    """update_stage should persist the artifact in the correct JSONB column."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Test spec", "TestProject")

    artifact = {"product_name": "TestProject", "user_stories": [{"id": "US-1"}]}
    await store.update_stage(pid, "business_analysis", artifact)

    row = await store.get_pipeline(pid)
    assert row is not None
    assert row["current_stage"] == "business_analysis"

    spec = row["product_spec"]
    assert isinstance(spec, dict)
    assert spec["product_name"] == "TestProject"
    assert len(spec["user_stories"]) == 1


@pytest.mark.asyncio
async def test_update_stage_all_columns(store: StateStore) -> None:
    """Each stage should map to the correct JSONB column."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Spec", "Proj")

    await store.update_stage(pid, "business_analysis", {"ba": True})
    await store.update_stage(pid, "research", {"research": True})
    await store.update_stage(pid, "architecture", {"arch": True})
    await store.update_stage(pid, "task_decomposition", {"prd": True})

    row = await store.get_pipeline(pid)
    assert row["product_spec"] == {"ba": True}
    assert row["enriched_spec"] == {"research": True}
    assert row["tech_spec"] == {"arch": True}
    assert row["prd_board"] == {"prd": True}


@pytest.mark.asyncio
async def test_update_cost_increments(store: StateStore) -> None:
    """update_cost should atomically increment total_cost_usd."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Spec", "Proj")

    await store.update_cost(pid, 0.005)
    await store.update_cost(pid, 0.003)
    await store.update_cost(pid, 0.002)

    row = await store.get_pipeline(pid)
    assert row is not None
    total = float(row["total_cost_usd"])
    assert abs(total - 0.010) < 1e-6


@pytest.mark.asyncio
async def test_record_ticket_execution_upsert(store: StateStore) -> None:
    """record_ticket_execution should insert on first call, update on conflict."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Spec", "Proj")

    # First call — insert
    await store.record_ticket_execution(
        pid,
        "FORGE-1",
        "in_progress",
        agent_id="agent-a",
        branch_name="forge/forge-1",
    )

    # Second call — update status, keep branch
    await store.record_ticket_execution(
        pid,
        "FORGE-1",
        "completed",
    )

    pool = await store._get_pool()  # noqa: SLF001
    row = await pool.fetchrow(
        "SELECT * FROM ticket_executions WHERE pipeline_id = $1 AND ticket_key = $2",
        pid,
        "FORGE-1",
    )
    assert row is not None
    assert row["status"] == "completed"
    # Original branch should be preserved via COALESCE
    assert row["branch_name"] == "forge/forge-1"


@pytest.mark.asyncio
async def test_record_event_and_retrieval(store: StateStore) -> None:
    """record_event should insert, and the row should be queryable."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Spec", "Proj")

    await store.record_event(
        pid,
        agent_role="developer",
        event_type="task_started",
        payload={"stage": "coding", "ticket_key": "FORGE-1"},
        agent_id="coder-001",
    )

    pool = await store._get_pool()  # noqa: SLF001
    rows = await pool.fetch(
        "SELECT * FROM agent_events WHERE pipeline_id = $1 ORDER BY created_at DESC",
        pid,
    )
    assert len(rows) >= 1
    row = rows[0]
    assert row["event_type"] == "task_started"
    assert row["agent_role"] == "developer"
    assert row["agent_id"] == "coder-001"


@pytest.mark.asyncio
async def test_update_status_sets_completed_at(store: StateStore) -> None:
    """Terminal status should set completed_at timestamp."""
    pid = _uid()
    await store.create_pipeline_run(pid, "Spec", "Proj")

    await store.update_status(pid, "completed")

    row = await store.get_pipeline(pid)
    assert row is not None
    assert row["status"] == "completed"
    assert row["completed_at"] is not None


@pytest.mark.asyncio
async def test_get_pipeline_not_found(store: StateStore) -> None:
    """get_pipeline should return None for a non-existent pipeline."""
    row = await store.get_pipeline("nonexistent-id-12345")
    assert row is None
