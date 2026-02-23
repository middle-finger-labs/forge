"""Structured state persistence layer for Forge pipelines.

Reads and writes pipeline artifacts to the ``forge_app`` PostgreSQL database,
replacing the approach where state only lives in Temporal workflow memory.

Usage::

    store = StateStore("postgresql://forge:forge@localhost:5432/forge_app")
    await store.create_pipeline_run("abc123", "Build a TODO app", "TodoApp")
    await store.update_stage("abc123", "business_analysis", {"product_name": "TodoApp"})
    await store.close()
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger().bind(component="state_store")

# ---------------------------------------------------------------------------
# Stage → JSONB column mapping
# ---------------------------------------------------------------------------

_STAGE_COLUMN: dict[str, str] = {
    "business_analysis": "product_spec",
    "research": "enriched_spec",
    "architecture": "tech_spec",
    "task_decomposition": "prd_board",
}

_TERMINAL_STATUSES = frozenset({"complete", "completed", "failed", "aborted"})

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _retry(coro_factory, *, retries: int = _MAX_RETRIES, label: str = "db_op"):
    """Execute an async callable with exponential backoff retries.

    ``coro_factory`` must be a zero-argument callable that returns a new
    awaitable on each invocation (not a pre-built coroutine).
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await coro_factory()
        except (
            asyncpg.PostgresConnectionError,
            asyncpg.InterfaceError,
            OSError,
        ) as exc:
            last_exc = exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            log.warning(
                "retrying db operation",
                label=label,
                attempt=attempt,
                error=str(exc),
                next_delay=delay,
            )
            await asyncio.sleep(delay)
    log.error("db operation failed after retries", label=label, error=str(last_exc))
    raise last_exc  # type: ignore[misc]


def _json_dumps(obj: Any) -> str:
    """Serialise to JSON, handling non-standard types."""
    return json.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------


class StateStore:
    """Async PostgreSQL persistence for Forge pipeline state."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    # -- Pool management ----------------------------------------------------

    async def _get_pool(self) -> asyncpg.Pool:
        """Lazily create the connection pool on first use."""
        if self._pool is None or self._pool._closed:  # noqa: SLF001
            log.info("creating connection pool", dsn=self._dsn.split("@")[-1])
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=2,
                max_size=10,
            )
        return self._pool

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool and not self._pool._closed:  # noqa: SLF001
            await self._pool.close()
            log.info("connection pool closed")

    # -- Pipeline CRUD -------------------------------------------------------

    async def create_pipeline_run(
        self,
        pipeline_id: str,
        business_spec: str,
        project_name: str,
        org_id: str | None = None,
    ) -> None:
        """INSERT a new pipeline run."""
        pool = await self._get_pool()

        async def _insert():
            await pool.execute(
                """
                INSERT INTO pipeline_runs (pipeline_id, status, current_stage,
                                           business_spec, project_name, org_id)
                VALUES ($1, 'running', 'intake', $2, $3, $4)
                """,
                pipeline_id,
                business_spec,
                project_name,
                org_id,
            )

        await _retry(_insert, label="create_pipeline_run")
        log.info("pipeline run created", pipeline_id=pipeline_id, org_id=org_id)

    async def update_stage(
        self,
        pipeline_id: str,
        stage: str,
        artifact: dict,
    ) -> None:
        """UPDATE the JSONB artifact column for the given stage.

        Also advances ``current_stage`` and bumps ``updated_at``.
        """
        column = _STAGE_COLUMN.get(stage)
        if column is None:
            log.warning("no artifact column for stage", stage=stage)
            # Still update current_stage even if there's no artifact column
            pool = await self._get_pool()

            async def _update_stage_only():
                await pool.execute(
                    """
                    UPDATE pipeline_runs
                    SET current_stage = $1, updated_at = now()
                    WHERE pipeline_id = $2
                    """,
                    stage,
                    pipeline_id,
                )

            await _retry(_update_stage_only, label="update_stage_only")
            return

        pool = await self._get_pool()
        artifact_json = _json_dumps(artifact)

        # Build query dynamically but safely — the column name comes from our
        # own constant dict, never from user input.
        async def _update():
            await pool.execute(
                f"""
                UPDATE pipeline_runs
                SET {column} = $1::jsonb,
                    current_stage = $2,
                    updated_at = now()
                WHERE pipeline_id = $3
                """,
                artifact_json,
                stage,
                pipeline_id,
            )

        await _retry(_update, label="update_stage")
        log.info("stage updated", pipeline_id=pipeline_id, stage=stage, column=column)

    async def update_status(self, pipeline_id: str, status: str) -> None:
        """UPDATE pipeline status. Sets ``completed_at`` for terminal statuses."""
        pool = await self._get_pool()

        if status in _TERMINAL_STATUSES:

            async def _update():
                await pool.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = $1, updated_at = now(), completed_at = now()
                    WHERE pipeline_id = $2
                    """,
                    status,
                    pipeline_id,
                )
        else:

            async def _update():
                await pool.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = $1, updated_at = now()
                    WHERE pipeline_id = $2
                    """,
                    status,
                    pipeline_id,
                )

        await _retry(_update, label="update_status")
        log.info("status updated", pipeline_id=pipeline_id, status=status)

    async def update_cost(self, pipeline_id: str, cost_delta: float) -> None:
        """Atomically increment ``total_cost_usd`` by *cost_delta*."""
        pool = await self._get_pool()

        async def _update():
            await pool.execute(
                """
                UPDATE pipeline_runs
                SET total_cost_usd = total_cost_usd + $1,
                    updated_at = now()
                WHERE pipeline_id = $2
                """,
                cost_delta,
                pipeline_id,
            )

        await _retry(_update, label="update_cost")
        log.info("cost updated", pipeline_id=pipeline_id, delta=cost_delta)

    async def get_pipeline(self, pipeline_id: str, org_id: str | None = None) -> dict | None:
        """SELECT full pipeline row as a dict, optionally scoped to org."""
        pool = await self._get_pool()

        async def _select():
            if org_id is not None:
                row = await pool.fetchrow(
                    """
                    SELECT id, pipeline_id, status, current_stage, business_spec,
                           project_name, total_cost_usd, product_spec, enriched_spec,
                           tech_spec, prd_board, created_at, updated_at, completed_at
                    FROM pipeline_runs
                    WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
                    """,
                    pipeline_id,
                    org_id,
                )
            else:
                row = await pool.fetchrow(
                    """
                    SELECT id, pipeline_id, status, current_stage, business_spec,
                           project_name, total_cost_usd, product_spec, enriched_spec,
                           tech_spec, prd_board, created_at, updated_at, completed_at
                    FROM pipeline_runs
                    WHERE pipeline_id = $1
                    """,
                    pipeline_id,
                )
            if row is None:
                return None
            result = dict(row)
            # Decode JSONB columns stored as strings
            for col in ("product_spec", "enriched_spec", "tech_spec", "prd_board"):
                val = result.get(col)
                if isinstance(val, str):
                    try:
                        result[col] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
            return result

        result = await _retry(_select, label="get_pipeline")
        return result

    # -- Ticket operations ---------------------------------------------------

    async def record_ticket_execution(
        self,
        pipeline_id: str,
        ticket_id: str,
        status: str,
        agent_id: str | None = None,
        branch_name: str | None = None,
        org_id: str | None = None,
    ) -> None:
        """UPSERT a ticket execution row."""
        pool = await self._get_pool()

        async def _upsert():
            await pool.execute(
                """
                INSERT INTO ticket_executions
                    (pipeline_id, ticket_key, status, agent_id, branch_name, org_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (pipeline_id, ticket_key)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    agent_id = COALESCE(EXCLUDED.agent_id, ticket_executions.agent_id),
                    branch_name = COALESCE(EXCLUDED.branch_name, ticket_executions.branch_name),
                    org_id = COALESCE(EXCLUDED.org_id, ticket_executions.org_id),
                    updated_at = now()
                """,
                pipeline_id,
                ticket_id,
                status,
                agent_id,
                branch_name,
                org_id,
            )

        await _retry(_upsert, label="record_ticket_execution")
        log.info(
            "ticket execution recorded",
            pipeline_id=pipeline_id,
            ticket_id=ticket_id,
            status=status,
        )

    async def update_ticket_result(
        self,
        pipeline_id: str,
        ticket_id: str,
        code_artifact: dict | None,
        qa_reviews: list[dict],
        revision_count: int,
        status: str,
        cost_usd: float,
        verdict: str | None = None,
    ) -> None:
        """UPDATE a ticket execution with coding / QA results."""
        pool = await self._get_pool()
        code_json = _json_dumps(code_artifact) if code_artifact else None
        qa_json = _json_dumps(qa_reviews) if qa_reviews else None

        async def _update():
            await pool.execute(
                """
                UPDATE ticket_executions
                SET code_artifact = COALESCE($1::jsonb, code_artifact),
                    qa_review     = COALESCE($2::jsonb, qa_review),
                    attempts      = $3,
                    status        = $4,
                    cost_usd      = CASE WHEN $5 > 0 THEN $5 ELSE cost_usd END,
                    verdict       = COALESCE($6, verdict),
                    updated_at    = now()
                WHERE pipeline_id = $7
                  AND ticket_key  = $8
                """,
                code_json,
                qa_json,
                revision_count,
                status,
                cost_usd,
                verdict,
                pipeline_id,
                ticket_id,
            )

        await _retry(_update, label="update_ticket_result")
        log.info(
            "ticket result updated",
            pipeline_id=pipeline_id,
            ticket_id=ticket_id,
            status=status,
        )

    # -- Events --------------------------------------------------------------

    async def record_event(
        self,
        pipeline_id: str,
        agent_role: str,
        event_type: str,
        payload: dict,
        agent_id: str | None = None,
        org_id: str | None = None,
    ) -> None:
        """INSERT an agent event row."""
        pool = await self._get_pool()
        payload_json = _json_dumps(payload)

        async def _insert():
            await pool.execute(
                """
                INSERT INTO agent_events
                    (pipeline_id, event_type, stage, agent_role, agent_id, payload, org_id)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                """,
                pipeline_id,
                event_type,
                payload.get("stage"),
                agent_role,
                agent_id,
                payload_json,
                org_id,
            )

        await _retry(_insert, label="record_event")

    # -- CTO interventions ---------------------------------------------------

    async def record_cto_intervention(
        self,
        pipeline_id: str,
        trigger_type: str,
        trigger_description: str,
        decision: dict,
        org_id: str | None = None,
    ) -> None:
        """INSERT a CTO intervention record."""
        pool = await self._get_pool()
        decision_json = _json_dumps(decision)

        async def _insert():
            await pool.execute(
                """
                INSERT INTO cto_interventions
                    (pipeline_id, trigger_type, trigger_description, decision, org_id)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                """,
                pipeline_id,
                trigger_type,
                trigger_description,
                decision_json,
                org_id,
            )

        await _retry(_insert, label="record_cto_intervention")
        log.info(
            "cto intervention recorded",
            pipeline_id=pipeline_id,
            trigger_type=trigger_type,
        )

    # -- History / learning ---------------------------------------------------

    async def get_pipeline_history(self, limit: int = 10, org_id: str | None = None) -> list[dict]:
        """SELECT recent completed pipelines for memory / learning purposes."""
        pool = await self._get_pool()

        async def _select():
            if org_id is not None:
                rows = await pool.fetch(
                    """
                    SELECT id, pipeline_id, status, current_stage, project_name,
                           total_cost_usd, created_at, completed_at
                    FROM pipeline_runs
                    WHERE status IN ('complete', 'completed', 'failed')
                      AND (org_id = $2 OR org_id IS NULL)
                    ORDER BY completed_at DESC NULLS LAST
                    LIMIT $1
                    """,
                    limit,
                    org_id,
                )
            else:
                rows = await pool.fetch(
                    """
                    SELECT id, pipeline_id, status, current_stage, project_name,
                           total_cost_usd, created_at, completed_at
                    FROM pipeline_runs
                    WHERE status IN ('complete', 'completed', 'failed')
                    ORDER BY completed_at DESC NULLS LAST
                    LIMIT $1
                    """,
                    limit,
                )
            return [dict(r) for r in rows]

        return await _retry(_select, label="get_pipeline_history")


# ---------------------------------------------------------------------------
# Main — end-to-end smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    async def main():
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
        )
        store = StateStore(dsn)

        test_id = "smoke-test-001"

        try:
            # 1. Create a pipeline run
            print(f"[1] Creating pipeline run '{test_id}'...")
            await store.create_pipeline_run(
                test_id,
                business_spec="Build a real-time chat application with rooms.",
                project_name="ChatApp",
            )

            # 2. Walk through stages
            print("[2] Updating through stages...")

            await store.update_stage(
                test_id,
                "business_analysis",
                {
                    "product_name": "ChatApp",
                    "product_vision": "A real-time chat app with rooms and DMs",
                    "user_stories": [
                        {"id": "US-001", "persona": "user", "action": "send message"},
                    ],
                },
            )

            await store.update_stage(
                test_id,
                "research",
                {
                    "original_spec": {"product_name": "ChatApp"},
                    "research_findings": [{"topic": "WebSocket", "summary": "Use WS"}],
                },
            )

            await store.update_stage(
                test_id,
                "architecture",
                {
                    "spec_id": "TECH-001",
                    "tech_stack": {"language": "Python 3.12", "ws": "FastAPI"},
                    "services": [{"name": "chat-service", "responsibility": "messaging"}],
                },
            )

            await store.update_stage(
                test_id,
                "task_decomposition",
                {
                    "board_id": "BOARD-001",
                    "tickets": [
                        {"ticket_key": "FORGE-1", "title": "WebSocket server"},
                        {"ticket_key": "FORGE-2", "title": "Room management"},
                    ],
                    "execution_order": [["FORGE-1"], ["FORGE-2"]],
                },
            )

            # 3. Update cost
            print("[3] Updating cost...")
            await store.update_cost(test_id, 0.0042)
            await store.update_cost(test_id, 0.0018)

            # 4. Record ticket executions
            print("[4] Recording ticket executions...")
            await store.record_ticket_execution(
                test_id,
                "FORGE-1",
                "in_progress",
                agent_id="coder-001",
                branch_name="forge/FORGE-1",
            )
            await store.record_ticket_execution(
                test_id,
                "FORGE-2",
                "in_progress",
                agent_id="coder-002",
                branch_name="forge/FORGE-2",
            )

            # 5. Update ticket results
            print("[5] Updating ticket results...")
            await store.update_ticket_result(
                test_id,
                "FORGE-1",
                code_artifact={
                    "ticket_key": "FORGE-1",
                    "git_branch": "forge/FORGE-1",
                    "files_created": ["src/ws_server.py"],
                },
                qa_reviews=[{"verdict": "approved", "score": 8}],
                revision_count=1,
                status="approved",
                cost_usd=0.003,
            )

            # 6. Record an event
            print("[6] Recording events...")
            await store.record_event(
                test_id,
                agent_role="developer",
                event_type="task_started",
                payload={"stage": "coding", "ticket_key": "FORGE-1"},
                agent_id="coder-001",
            )

            # 7. Record CTO intervention
            print("[7] Recording CTO intervention...")
            await store.record_cto_intervention(
                test_id,
                trigger_type="budget_warning",
                trigger_description="Cost at 80% of budget",
                decision={"action": "continue", "rationale": "On track"},
            )

            # 8. Complete the pipeline
            print("[8] Completing pipeline...")
            await store.update_status(test_id, "complete")

            # 9. Read it back
            print("[9] Reading pipeline back...")
            pipeline = await store.get_pipeline(test_id)
            if pipeline:
                print(f"    pipeline_id:  {pipeline['pipeline_id']}")
                print(f"    status:       {pipeline['status']}")
                print(f"    stage:        {pipeline['current_stage']}")
                print(f"    cost:         ${float(pipeline['total_cost_usd']):.4f}")
                print(f"    project:      {pipeline['project_name']}")
                print(
                    f"    has specs:    "
                    f"product={pipeline['product_spec'] is not None}, "
                    f"enriched={pipeline['enriched_spec'] is not None}, "
                    f"tech={pipeline['tech_spec'] is not None}, "
                    f"prd={pipeline['prd_board'] is not None}"
                )
                print(f"    completed_at: {pipeline['completed_at']}")
            else:
                print("    ERROR: pipeline not found!")

            # 10. Check history
            print("[10] Querying pipeline history...")
            history = await store.get_pipeline_history(limit=5)
            print(f"    {len(history)} completed pipeline(s) found")

            print("\nAll smoke tests passed.")

        finally:
            # Clean up test data
            pool = await store._get_pool()  # noqa: SLF001
            await pool.execute(
                "DELETE FROM agent_events WHERE pipeline_id = $1",
                test_id,
            )
            await pool.execute(
                "DELETE FROM cto_interventions WHERE pipeline_id = $1",
                test_id,
            )
            await pool.execute(
                "DELETE FROM ticket_executions WHERE pipeline_id = $1",
                test_id,
            )
            await pool.execute(
                "DELETE FROM pipeline_runs WHERE pipeline_id = $1",
                test_id,
            )
            print("Test data cleaned up.")
            await store.close()

    asyncio.run(main())
