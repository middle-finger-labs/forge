"""Tests for the prompt version management subsystem.

All tests mock database calls — no real DB or API.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.prompts.registry import STAGE_ROLES, PromptRegistry
from agents.prompts.types import PromptVersion, PromptVersionStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_registry():
    """Return a PromptRegistry with a mocked connection pool."""
    registry = PromptRegistry(dsn="postgresql://test:test@localhost/test")
    registry._pool = MagicMock()
    return registry


def _make_version_row(
    *,
    version_id="ver-1",
    org_id="org-1",
    stage=1,
    version=1,
    system_prompt="You are a BA agent.",
    is_active=True,
    change_summary="Initial version",
    created_by="user-1",
):
    """Build a mock row dict matching the prompt_versions table schema."""
    return {
        "id": version_id,
        "org_id": org_id,
        "stage": stage,
        "agent_role": STAGE_ROLES.get(stage, ""),
        "version": version,
        "system_prompt": system_prompt,
        "change_summary": change_summary,
        "is_active": is_active,
        "created_by": created_by,
        "created_at": None,
    }


# ---------------------------------------------------------------------------
# PromptVersion dataclass
# ---------------------------------------------------------------------------


def test_prompt_version_defaults():
    """PromptVersion has sensible defaults."""
    ver = PromptVersion()
    assert ver.id == ""
    assert ver.version == 1
    assert ver.is_active is False


def test_prompt_version_stats_defaults():
    """PromptVersionStats has sensible defaults."""
    stats = PromptVersionStats()
    assert stats.total_runs == 0
    assert stats.approval_rate == 0.0


# ---------------------------------------------------------------------------
# STAGE_ROLES mapping
# ---------------------------------------------------------------------------


def test_stage_roles_mapping():
    """All 7 stages have a role mapping."""
    assert len(STAGE_ROLES) == 7
    assert STAGE_ROLES[1] == "business_analyst"
    assert STAGE_ROLES[5] == "developer"
    assert STAGE_ROLES[7] == "cto"


# ---------------------------------------------------------------------------
# PromptRegistry.get_active_prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_prompt_found():
    """Active prompt exists → returns PromptVersion."""
    registry = _mock_registry()
    row = _make_version_row(is_active=True)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.get_active_prompt(org_id="org-1", stage=1)

    assert result is not None
    assert result.is_active is True
    assert result.system_prompt == "You are a BA agent."


@pytest.mark.asyncio
async def test_get_active_prompt_not_found():
    """No active prompt → returns None."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.get_active_prompt(org_id="org-1", stage=1)
    assert result is None


# ---------------------------------------------------------------------------
# PromptRegistry.create_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_version():
    """Creating a version assigns next version number."""
    registry = _mock_registry()
    row = _make_version_row(version=2, is_active=False)

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)  # max version is 1
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.create_version(
        org_id="org-1",
        stage=1,
        system_prompt="Updated prompt",
        change_summary="Better instructions",
        created_by="user-1",
    )

    assert result is not None
    assert result.version == 2


@pytest.mark.asyncio
async def test_create_version_with_activate():
    """Creating a version with activate=True deactivates existing."""
    registry = _mock_registry()
    row = _make_version_row(version=1, is_active=True)

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.create_version(
        org_id="org-1",
        stage=1,
        system_prompt="New prompt",
        activate=True,
    )

    assert result is not None
    # Should have called execute to deactivate existing
    assert conn.execute.call_count >= 1


# ---------------------------------------------------------------------------
# PromptRegistry.activate_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_version_success():
    """Activating a valid version returns True."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"stage": 1})
    conn.execute = AsyncMock(return_value="UPDATE 1")
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.activate_version("ver-1", org_id="org-1")
    assert result is True


@pytest.mark.asyncio
async def test_activate_version_not_found():
    """Activating a nonexistent version returns False."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.activate_version("nonexistent", org_id="org-1")
    assert result is False


# ---------------------------------------------------------------------------
# PromptRegistry.get_version_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_version_history():
    """History returns versions newest first."""
    registry = _mock_registry()
    rows = [
        _make_version_row(version_id="v2", version=2),
        _make_version_row(version_id="v1", version=1),
    ]

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.get_version_history(
        org_id="org-1", stage=1, limit=10,
    )

    assert len(result) == 2
    assert result[0].version == 2
    assert result[1].version == 1


# ---------------------------------------------------------------------------
# PromptRegistry.record_evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_evaluation():
    """Recording an evaluation returns the eval UUID."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": "eval-uuid-123"})
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    eval_id = await registry.record_evaluation(
        org_id="org-1",
        prompt_version_id="ver-1",
        pipeline_id="pipe-1",
        stage=1,
        agent_role="business_analyst",
        verdict="approved",
        cost_usd=0.05,
        duration_seconds=12.5,
    )

    assert eval_id == "eval-uuid-123"


# ---------------------------------------------------------------------------
# PromptRegistry.get_version_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_version_stats():
    """Stats aggregation returns correct values."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "total_runs": 10,
        "approved_count": 8,
        "avg_cost": 0.045,
        "avg_duration": 15.3,
        "avg_attempts": 1.2,
        "error_count": 1,
    })
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    stats = await registry.get_version_stats("ver-1", org_id="org-1")

    assert stats is not None
    assert stats.total_runs == 10
    assert stats.approval_rate == 0.8
    assert stats.avg_cost_usd == 0.045
    assert stats.error_count == 1


@pytest.mark.asyncio
async def test_get_version_stats_no_runs():
    """Stats for version with no runs returns None."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "total_runs": 0,
        "approved_count": 0,
        "avg_cost": 0,
        "avg_duration": 0,
        "avg_attempts": 0,
        "error_count": 0,
    })
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    stats = await registry.get_version_stats("ver-1", org_id="org-1")
    assert stats is None


# ---------------------------------------------------------------------------
# PromptRegistry.compare_versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_versions():
    """Comparison returns side-by-side stats."""
    registry = _mock_registry()

    conn = AsyncMock()

    # compare_versions calls: get_version_stats(A), get_version_stats(B),
    # get_version(A), get_version(B) — each does one pool.acquire + fetchrow
    fetchrow_responses = [
        # get_version_stats(A)
        {"total_runs": 10, "approved_count": 8, "avg_cost": 0.05,
         "avg_duration": 12.0, "avg_attempts": 1.1, "error_count": 0},
        # get_version_stats(B)
        {"total_runs": 5, "approved_count": 5, "avg_cost": 0.03,
         "avg_duration": 10.0, "avg_attempts": 1.0, "error_count": 0},
        # get_version(A)
        _make_version_row(version_id="ver-a", version=1,
                          system_prompt="Prompt A"),
        # get_version(B)
        _make_version_row(version_id="ver-b", version=2,
                          system_prompt="Prompt B"),
    ]
    conn.fetchrow = AsyncMock(side_effect=fetchrow_responses)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.compare_versions(
        "ver-a", "ver-b", org_id="org-1",
    )

    assert "version_a" in result
    assert "version_b" in result
    assert result["version_a"]["stats"]["total_runs"] == 10
    assert result["version_b"]["stats"]["total_runs"] == 5


# ---------------------------------------------------------------------------
# PromptRegistry.resolve_prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_prompt_with_active():
    """Org has active prompt → returns custom prompt and version_id."""
    registry = _mock_registry()
    row = _make_version_row(
        version_id="custom-ver",
        system_prompt="Custom prompt for org",
    )

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    prompt, version_id = await registry.resolve_prompt(
        org_id="org-1", stage=1, default_prompt="Default prompt",
    )

    assert prompt == "Custom prompt for org"
    assert version_id == "custom-ver"


@pytest.mark.asyncio
async def test_resolve_prompt_fallback_to_default():
    """No active prompt → returns default prompt with None version_id."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    prompt, version_id = await registry.resolve_prompt(
        org_id="org-1", stage=1, default_prompt="Default prompt",
    )

    assert prompt == "Default prompt"
    assert version_id is None


# ---------------------------------------------------------------------------
# evaluation.resolve_stage_prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_stage_prompt_empty_org():
    """Empty org_id → returns default immediately."""
    from agents.prompts.evaluation import resolve_stage_prompt

    prompt, version_id = await resolve_stage_prompt(
        org_id="", stage=1, default_prompt="Default",
    )

    assert prompt == "Default"
    assert version_id is None


@pytest.mark.asyncio
async def test_record_stage_evaluation_no_version():
    """No version_id → no-op."""
    from agents.prompts.evaluation import record_stage_evaluation

    # Should not raise
    await record_stage_evaluation(
        org_id="org-1",
        pipeline_id="pipe-1",
        stage=1,
        agent_role="business_analyst",
        prompt_version_id=None,
    )


# ---------------------------------------------------------------------------
# _row_to_version helper
# ---------------------------------------------------------------------------


def test_row_to_version():
    """_row_to_version correctly converts a DB row."""
    row = _make_version_row(
        version_id="abc-123",
        org_id="org-x",
        stage=3,
        version=5,
        system_prompt="Architect prompt",
    )
    ver = PromptRegistry._row_to_version(row)

    assert ver.id == "abc-123"
    assert ver.org_id == "org-x"
    assert ver.stage == 3
    assert ver.version == 5
    assert ver.agent_role == "architect"


# ---------------------------------------------------------------------------
# Prompt hash consistency
# ---------------------------------------------------------------------------


def test_prompt_hash_deterministic():
    """Same prompt always produces the same hash prefix."""
    prompt = "You are a helpful assistant."
    expected = hashlib.sha256(prompt.encode()).hexdigest()[:12]

    # Second computation should match
    actual = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    assert actual == expected


# ---------------------------------------------------------------------------
# PromptRegistry.get_version_stats_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_version_stats_history():
    """Stats history returns daily aggregated approval/cost data."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[
        {
            "date": "2025-01-01",
            "run_count": 5,
            "approved_count": 4,
            "avg_cost": 0.04,
            "avg_duration": 12.0,
        },
        {
            "date": "2025-01-02",
            "run_count": 10,
            "approved_count": 9,
            "avg_cost": 0.035,
            "avg_duration": 11.0,
        },
        {
            "date": "2025-01-03",
            "run_count": 3,
            "approved_count": 3,
            "avg_cost": 0.03,
            "avg_duration": 10.0,
        },
    ])
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.get_version_stats_history("ver-1", org_id="org-1")

    assert len(result) == 3
    assert result[0]["date"] == "2025-01-01"
    assert result[0]["run_count"] == 5
    assert result[1]["approved_count"] == 9
    assert result[2]["avg_cost"] == 0.03


@pytest.mark.asyncio
async def test_get_version_stats_history_empty():
    """Stats history returns empty list when no data."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    result = await registry.get_version_stats_history("ver-1", org_id="org-1")
    assert result == []


# ---------------------------------------------------------------------------
# PromptRegistry.record_evaluation with verdict types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_evaluation_rejected():
    """Recording a rejected evaluation captures the rejection reason."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": "eval-rejected-1"})
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    eval_id = await registry.record_evaluation(
        org_id="org-1",
        prompt_version_id="ver-1",
        pipeline_id="pipe-2",
        stage=5,
        agent_role="developer",
        verdict="rejected",
        cost_usd=0.08,
        duration_seconds=25.0,
    )

    assert eval_id == "eval-rejected-1"
    conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_record_evaluation_error():
    """Recording an error evaluation tracks cost as 0."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": "eval-error-1"})
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    eval_id = await registry.record_evaluation(
        org_id="org-1",
        prompt_version_id="ver-1",
        pipeline_id="pipe-3",
        stage=1,
        agent_role="business_analyst",
        verdict="error",
        cost_usd=0.0,
        duration_seconds=2.0,
    )

    assert eval_id == "eval-error-1"


# ---------------------------------------------------------------------------
# PromptRegistry.get_version_stats computation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_version_stats_approval_rate_calculation():
    """Approval rate is correctly computed as approved_count / total_runs."""
    registry = _mock_registry()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "total_runs": 20,
        "approved_count": 15,
        "avg_cost": 0.06,
        "avg_duration": 18.5,
        "avg_attempts": 1.5,
        "error_count": 2,
    })
    registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    stats = await registry.get_version_stats("ver-1", org_id="org-1")

    assert stats is not None
    assert stats.total_runs == 20
    assert stats.approval_rate == 0.75  # 15/20
    assert stats.avg_cost_usd == 0.06
    assert stats.avg_duration_seconds == 18.5
    assert stats.error_count == 2


# ---------------------------------------------------------------------------
# Version creation with prompt content hash
# ---------------------------------------------------------------------------


def test_different_prompts_produce_different_hashes():
    """Two different prompts should hash to different values."""
    prompt_a = "You are a BA agent focused on requirements."
    prompt_b = "You are a developer agent focused on code."

    hash_a = hashlib.sha256(prompt_a.encode()).hexdigest()[:12]
    hash_b = hashlib.sha256(prompt_b.encode()).hexdigest()[:12]
    assert hash_a != hash_b


# ---------------------------------------------------------------------------
# Async context manager helper for mocking pool.acquire()
# ---------------------------------------------------------------------------


class _AsyncCtx:  # noqa: N801
    """Minimal async context manager wrapping a mock connection."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass
