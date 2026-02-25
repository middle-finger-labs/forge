"""Tests for the prompt test-run endpoint and stats history.

All tests mock database and LLM calls — no real services needed.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from api.routes.prompts import prompts_router, pipeline_router

# ---------------------------------------------------------------------------
# App fixture with mocked auth
# ---------------------------------------------------------------------------


class FakeUser:
    user_id = "user-1"
    org_id = "org-1"


def _fake_get_current_user():
    return FakeUser()


app = FastAPI()
app.include_router(prompts_router)
app.include_router(pipeline_router)

# Override auth dependency globally
app.dependency_overrides = {}


@pytest.fixture()
def client():
    """Return an async test client with mocked auth."""
    from auth.middleware import get_current_user

    app.dependency_overrides[get_current_user] = _fake_get_current_user
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# POST /api/prompts/test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_test_run_success(client):
    """Successful test-run returns output, cost, and duration."""
    mock_output = {"name": "Test Product", "features": []}

    with patch("agents.langgraph_runner.run_agent", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (mock_output, 0.05)

        fake_model = MagicMock()
        with patch("api.routes.prompts._get_stage_models", return_value={1: fake_model}):
            resp = await client.post(
                "/api/prompts/test",
                json={
                    "stage": 1,
                    "system_prompt": "You are a test BA agent.",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["output"] == mock_output
    assert data["cost_usd"] == 0.05
    assert data["error"] is None
    assert "duration_seconds" in data


@pytest.mark.asyncio
async def test_prompt_test_run_invalid_stage(client):
    """Stage out of range returns 400."""
    resp = await client.post(
        "/api/prompts/test",
        json={
            "stage": 99,
            "system_prompt": "Invalid",
        },
    )

    assert resp.status_code == 400
    assert "Stage must be 1-7" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_prompt_test_run_error_handled(client):
    """LLM error is returned gracefully, not as a 500."""
    with patch("agents.langgraph_runner.run_agent", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("LLM timeout")

        fake_model = MagicMock()
        with patch("api.routes.prompts._get_stage_models", return_value={1: fake_model}):
            resp = await client.post(
                "/api/prompts/test",
                json={
                    "stage": 1,
                    "system_prompt": "You are a test agent.",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["output"] is None
    assert "LLM timeout" in data["error"]
    assert data["cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/prompts/versions/{id}/stats/history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_stats_history(client):
    """Stats history returns daily aggregated data."""
    mock_history = [
        {"date": "2025-01-01", "approval_rate": 0.8, "avg_cost_usd": 0.04, "run_count": 5},
        {"date": "2025-01-02", "approval_rate": 0.9, "avg_cost_usd": 0.035, "run_count": 10},
    ]

    mock_registry = MagicMock()
    mock_registry.get_version_stats_history = AsyncMock(return_value=mock_history)

    with patch("api.routes.prompts._get_registry", return_value=mock_registry):
        resp = await client.get("/api/prompts/versions/ver-1/stats/history")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["date"] == "2025-01-01"
    assert data[0]["approval_rate"] == 0.8
    assert data[1]["run_count"] == 10


# ---------------------------------------------------------------------------
# GET /api/pipelines/{id}/summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_summary(client):
    """Pipeline summary aggregates per-agent stats."""
    mock_rows = [
        {
            "agent_role": "business_analyst",
            "verdict": "approved",
            "attempts": 1,
            "cost_usd": 0.04,
            "duration_seconds": 12.0,
            "error": None,
        },
        {
            "agent_role": "developer",
            "verdict": "approved",
            "attempts": 2,
            "cost_usd": 0.12,
            "duration_seconds": 45.0,
            "error": None,
        },
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_AsyncCtx(mock_conn))

    mock_registry = MagicMock()
    mock_registry._ensure_pool = AsyncMock(return_value=mock_pool)

    with patch("api.routes.prompts._get_registry", return_value=mock_registry):
        resp = await client.get("/api/pipelines/pipe-1/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["pipeline_id"] == "pipe-1"
    assert data["total_cost_usd"] == 0.16
    assert "business_analyst" in data["per_agent"]
    assert data["per_agent"]["business_analyst"]["first_pass"] is True
    assert data["per_agent"]["developer"]["first_pass"] is False
    assert data["per_agent"]["developer"]["attempts"] == 2


@pytest.mark.asyncio
async def test_pipeline_summary_not_found(client):
    """Missing pipeline returns 404."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_AsyncCtx(mock_conn))

    mock_registry = MagicMock()
    mock_registry._ensure_pool = AsyncMock(return_value=mock_pool)

    with patch("api.routes.prompts._get_registry", return_value=mock_registry):
        resp = await client.get("/api/pipelines/nonexistent/summary")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Async context manager helper
# ---------------------------------------------------------------------------


class _AsyncCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass
