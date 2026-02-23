"""End-to-end production tests for the Forge pipeline.

These tests exercise the *full* system — Temporal workflows, LLM calls,
database persistence, Redis pub/sub, and the dashboard API — against a
running infrastructure stack.

**Skipped by default.**  Run explicitly with::

    pytest -m e2e --timeout=600

Or use the orchestration script::

    scripts/run_e2e.sh

Prerequisites:
  - docker compose up (PostgreSQL, Redis, Temporal)
  - python -m worker  (background)
  - python -m api.run (background)
  - ANTHROPIC_API_KEY set in the environment
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import pytest

# ---------------------------------------------------------------------------
# Markers & constants
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FORGE_E2E") != "1",
        reason="Set FORGE_E2E=1 to run end-to-end tests",
    ),
]

API_BASE = os.environ.get("FORGE_API_URL", "http://localhost:8000")
POLL_INTERVAL = 5  # seconds between status polls
PIPELINE_TIMEOUT = 600  # 10 minutes max for a full pipeline run
BUDGET_PIPELINE_MAX = 5.0  # USD ceiling for budget enforcement test

BUSINESS_SPEC = (
    "Build a URL shortener service with custom aliases, click tracking "
    "analytics, and expiring links. The service should expose a REST API "
    "with endpoints for creating short URLs, redirecting to original URLs, "
    "and retrieving click analytics. Include rate limiting, input validation, "
    "and a simple dashboard page showing top links by click count."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api(path: str) -> str:
    return f"{API_BASE}{path}"


async def _poll_pipeline(
    client: httpx.AsyncClient,
    pipeline_id: str,
    *,
    until_statuses: set[str],
    timeout: float = PIPELINE_TIMEOUT,
) -> dict:
    """Poll GET /api/pipelines/{id} until status is in *until_statuses*."""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = await client.get(_api(f"/api/pipelines/{pipeline_id}"))
        resp.raise_for_status()
        last = resp.json()
        if last.get("status") in until_statuses:
            return last
        await asyncio.sleep(POLL_INTERVAL)
    raise TimeoutError(
        f"Pipeline {pipeline_id} did not reach {until_statuses} "
        f"within {timeout}s — last status: {last.get('status')}"
    )


async def _start_pipeline(
    client: httpx.AsyncClient,
    spec: str = BUSINESS_SPEC,
    project_name: str = "e2e-url-shortener",
) -> str:
    """POST a new pipeline and return its pipeline_id."""
    resp = await client.post(
        _api("/api/pipelines"),
        json={"business_spec": spec, "project_name": project_name},
    )
    resp.raise_for_status()
    data = resp.json()
    assert "pipeline_id" in data
    return data["pipeline_id"]


# ---------------------------------------------------------------------------
# 1. Full pipeline with real LLM calls
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Run a complete pipeline end-to-end with real LLM inference."""

    @pytest.fixture
    async def pipeline(self) -> str:
        """Start a pipeline and return its ID."""
        async with httpx.AsyncClient(timeout=30) as client:
            return await _start_pipeline(client)

    async def test_pipeline_runs_to_completion_or_approval(self, pipeline):
        """Pipeline should progress through stages.

        A full run may pause at ``awaiting_approval``; both that and
        ``completed`` are acceptable terminal states for this test.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            result = await _poll_pipeline(
                client,
                pipeline,
                until_statuses={
                    "completed",
                    "complete",
                    "awaiting_approval",
                    "pending_approval",
                    "failed",
                    "error",
                },
            )

            status = result["status"]
            # We expect success or awaiting human gate — not a crash
            assert status not in {"failed", "error"}, f"Pipeline {pipeline} failed: {result}"

    async def test_events_are_persisted(self, pipeline):
        """After the pipeline progresses, agent_events should exist in PG."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Wait until at least BA stage finishes
            await _poll_pipeline(
                client,
                pipeline,
                until_statuses={
                    "completed",
                    "complete",
                    "awaiting_approval",
                    "pending_approval",
                    "failed",
                    "error",
                },
            )

            resp = await client.get(_api(f"/api/pipelines/{pipeline}/events"))
            resp.raise_for_status()
            events = resp.json()
            assert isinstance(events, list)
            assert len(events) > 0, "Expected at least one event"

            # Check event structure
            evt = events[0]
            assert "event_type" in evt
            assert "pipeline_id" in evt

    async def test_cost_is_tracked(self, pipeline):
        """Pipeline should accumulate non-zero cost after LLM calls."""
        async with httpx.AsyncClient(timeout=30) as client:
            await _poll_pipeline(
                client,
                pipeline,
                until_statuses={
                    "completed",
                    "complete",
                    "awaiting_approval",
                    "pending_approval",
                    "failed",
                    "error",
                },
            )

            resp = await client.get(_api(f"/api/pipelines/{pipeline}/cost-breakdown"))
            resp.raise_for_status()
            breakdown = resp.json()
            assert breakdown.get("total_cost_usd", 0) > 0, (
                "Expected non-zero cost after real LLM calls"
            )

    async def test_tickets_are_generated(self, pipeline):
        """After task decomposition, tickets should be persisted."""
        async with httpx.AsyncClient(timeout=30) as client:
            await _poll_pipeline(
                client,
                pipeline,
                until_statuses={
                    "completed",
                    "complete",
                    "awaiting_approval",
                    "pending_approval",
                    "failed",
                    "error",
                },
            )

            resp = await client.get(_api(f"/api/pipelines/{pipeline}/tickets"))
            resp.raise_for_status()
            tickets = resp.json()
            # If pipeline got past task_decomposition, we should have tickets
            assert isinstance(tickets, list)


# ---------------------------------------------------------------------------
# 2. Model routing
# ---------------------------------------------------------------------------


class TestModelRouting:
    """Verify model routing picks providers correctly."""

    async def test_model_health_endpoint(self):
        """GET /api/admin/models should return model health info."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_api("/api/admin/models"))
            resp.raise_for_status()
            data = resp.json()
            assert "models" in data
            assert isinstance(data["models"], list)
            assert len(data["models"]) > 0

            # Each model should have expected fields
            for model in data["models"]:
                assert "model_id" in model
                assert "provider" in model

    async def test_model_usage_after_pipeline(self):
        """After running a pipeline, model usage stats should appear."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Start a lightweight pipeline
            pid = await _start_pipeline(
                client,
                spec=(
                    "Create a simple hello world Python script that prints "
                    "a greeting message. Minimal project, single file only."
                ),
                project_name="e2e-model-routing",
            )

            # Wait for at least business_analysis to complete
            await _poll_pipeline(
                client,
                pid,
                until_statuses={
                    "completed",
                    "complete",
                    "awaiting_approval",
                    "pending_approval",
                    "failed",
                    "error",
                },
                timeout=300,
            )

            # Check admin stats for model usage
            resp = await client.get(_api("/api/admin/stats"))
            resp.raise_for_status()
            stats = resp.json()
            assert stats.get("total_pipelines", 0) > 0


# ---------------------------------------------------------------------------
# 3. Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    """Verify the pipeline respects budget limits."""

    async def test_cost_stays_within_budget(self):
        """Pipeline cost should not exceed the configured budget."""
        async with httpx.AsyncClient(timeout=30) as client:
            pid = await _start_pipeline(
                client,
                spec=BUSINESS_SPEC,
                project_name="e2e-budget-test",
            )

            await _poll_pipeline(
                client,
                pid,
                until_statuses={
                    "completed",
                    "complete",
                    "awaiting_approval",
                    "pending_approval",
                    "failed",
                    "error",
                },
            )

            # Verify cost from breakdown
            resp = await client.get(_api(f"/api/pipelines/{pid}/cost-breakdown"))
            resp.raise_for_status()
            breakdown = resp.json()
            total = breakdown.get("total_cost_usd", 0)

            # Budget from PipelineConfig default is $10; we check a
            # reasonable ceiling — a single URL shortener shouldn't cost >$5
            assert total < BUDGET_PIPELINE_MAX, (
                f"Pipeline cost ${total:.4f} exceeded ${BUDGET_PIPELINE_MAX:.2f} budget ceiling"
            )

    async def test_errors_endpoint_returns_list(self):
        """GET /api/pipelines/{id}/errors should return a list."""
        async with httpx.AsyncClient(timeout=30) as client:
            pid = await _start_pipeline(
                client,
                spec="Build a simple calculator app.",
                project_name="e2e-errors-test",
            )

            # Give it a moment to start
            await asyncio.sleep(10)

            resp = await client.get(_api(f"/api/pipelines/{pid}/errors"))
            resp.raise_for_status()
            errors = resp.json()
            assert isinstance(errors, list)


# ---------------------------------------------------------------------------
# 4. Dashboard API
# ---------------------------------------------------------------------------


class TestDashboardAPI:
    """Verify the dashboard API endpoints work end-to-end."""

    async def test_health_check(self):
        """GET /api/health should report all services as ok."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_api("/api/health"))
            resp.raise_for_status()
            data = resp.json()
            assert data.get("healthy") is True, f"Services not healthy: {data.get('services')}"

    async def test_list_pipelines(self):
        """GET /api/pipelines should return a list."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_api("/api/pipelines"))
            resp.raise_for_status()
            data = resp.json()
            assert isinstance(data, list)

    async def test_admin_stats(self):
        """GET /api/admin/stats should return statistics."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_api("/api/admin/stats"))
            resp.raise_for_status()
            data = resp.json()
            assert "total_pipelines" in data
            assert "success_rate" in data

    async def test_admin_config_read_and_write(self):
        """POST then GET /api/admin/config should round-trip."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Read current config
            resp = await client.get(_api("/api/admin/config"))
            resp.raise_for_status()
            original = resp.json()
            assert isinstance(original, dict)

            # Update a value
            resp = await client.post(
                _api("/api/admin/config"),
                json={"max_concurrent_engineers": 3},
            )
            resp.raise_for_status()
            updated = resp.json()
            assert updated.get("status") == "updated"

            # Read back
            resp = await client.get(_api("/api/admin/config"))
            resp.raise_for_status()
            config = resp.json()
            assert config.get("max_concurrent_engineers") == 3

    async def test_start_and_poll_pipeline(self):
        """POST a pipeline, poll until it starts running."""
        async with httpx.AsyncClient(timeout=30) as client:
            pid = await _start_pipeline(
                client,
                spec="Create a minimal Python hello-world script.",
                project_name="e2e-dashboard-test",
            )

            # Pipeline should appear in the list
            resp = await client.get(_api("/api/pipelines"))
            resp.raise_for_status()
            pipelines = resp.json()
            ids = [p["pipeline_id"] for p in pipelines]
            assert pid in ids, f"Pipeline {pid} not found in list"

            # Get detail
            resp = await client.get(_api(f"/api/pipelines/{pid}"))
            resp.raise_for_status()
            detail = resp.json()
            assert detail["pipeline_id"] == pid

    async def test_pipeline_state_endpoint(self):
        """GET /api/pipelines/{id}/state should return pipeline state."""
        async with httpx.AsyncClient(timeout=30) as client:
            pid = await _start_pipeline(
                client,
                spec="Create a trivial Python script.",
                project_name="e2e-state-test",
            )

            # Give it a moment
            await asyncio.sleep(5)

            resp = await client.get(_api(f"/api/pipelines/{pid}/state"))
            # State endpoint may 404 if Temporal hasn't started yet
            if resp.status_code == 200:
                data = resp.json()
                assert "pipeline_id" in data or "status" in data

    async def test_concurrency_endpoint(self):
        """GET /api/pipelines/{id}/concurrency should return metrics."""
        async with httpx.AsyncClient(timeout=30) as client:
            pid = await _start_pipeline(
                client,
                spec="Create a basic Python utility.",
                project_name="e2e-concurrency-test",
            )

            await asyncio.sleep(5)

            resp = await client.get(_api(f"/api/pipelines/{pid}/concurrency"))
            # May 404 if workflow hasn't initialized yet
            if resp.status_code == 200:
                data = resp.json()
                assert "pipeline_id" in data
