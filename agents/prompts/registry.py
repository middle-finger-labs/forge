"""Prompt version registry backed by PostgreSQL.

Manages versioned system prompts per org and stage, with evaluation
tracking so orgs can iterate on agent prompts systematically.

Follows the same asyncpg connection-pool pattern as
:class:`agents.learning.lesson_store.LessonStore`.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import structlog

from agents.prompts.types import PromptVersion, PromptVersionStats

log = structlog.get_logger().bind(component="prompt_registry")

# ---------------------------------------------------------------------------
# Default stage → agent_role mapping (mirrors PROMPTS_BY_STAGE keys)
# ---------------------------------------------------------------------------

STAGE_ROLES = {
    1: "business_analyst",
    2: "research_analyst",
    3: "architect",
    4: "ticket_manager",
    5: "developer",
    6: "qa_engineer",
    7: "cto",
}


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
    )


_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    stage           INT NOT NULL,
    agent_role      TEXT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    system_prompt   TEXT NOT NULL,
    change_summary  TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_prompt_version UNIQUE (org_id, stage, version)
);

CREATE TABLE IF NOT EXISTS prompt_evaluations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            TEXT NOT NULL,
    prompt_version_id UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
    pipeline_id       TEXT NOT NULL,
    stage             INT NOT NULL,
    agent_role        TEXT NOT NULL,
    verdict           TEXT,
    attempts          INT NOT NULL DEFAULT 1,
    cost_usd          FLOAT NOT NULL DEFAULT 0.0,
    duration_seconds  FLOAT NOT NULL DEFAULT 0.0,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PromptRegistry:
    """Async registry for versioned agent prompts with evaluation tracking.

    Usage::

        registry = PromptRegistry()
        prompt = await registry.get_active_prompt(org_id="org-1", stage=5)
        if prompt:
            system_prompt = prompt.system_prompt
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _dsn()
        self._pool = None

    async def _ensure_pool(self):
        if self._pool is not None:
            return self._pool

        import asyncpg

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)

        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES_SQL)

        log.info("prompt registry pool created")
        return self._pool

    # ------------------------------------------------------------------
    # Version management
    # ------------------------------------------------------------------

    async def get_active_prompt(
        self, *, org_id: str, stage: int
    ) -> PromptVersion | None:
        """Return the currently active prompt version for an org/stage, or None."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, org_id, stage, agent_role, version, system_prompt,
                       change_summary, is_active, created_by, created_at
                FROM prompt_versions
                WHERE org_id = $1 AND stage = $2 AND is_active = TRUE
                """,
                org_id,
                stage,
            )

        if row is None:
            return None
        return self._row_to_version(row)

    async def create_version(
        self,
        *,
        org_id: str,
        stage: int,
        system_prompt: str,
        change_summary: str = "",
        created_by: str = "",
        activate: bool = False,
    ) -> PromptVersion:
        """Create a new prompt version for an org/stage.

        Automatically assigns the next version number. If *activate* is True,
        deactivates any existing active version first.
        """
        pool = await self._ensure_pool()
        agent_role = STAGE_ROLES.get(stage, "")

        async with pool.acquire() as conn:
            # Get next version number
            max_ver = await conn.fetchval(
                """
                SELECT COALESCE(MAX(version), 0)
                FROM prompt_versions
                WHERE org_id = $1 AND stage = $2
                """,
                org_id,
                stage,
            )
            next_version = max_ver + 1

            if activate:
                await conn.execute(
                    """
                    UPDATE prompt_versions SET is_active = FALSE
                    WHERE org_id = $1 AND stage = $2 AND is_active = TRUE
                    """,
                    org_id,
                    stage,
                )

            row = await conn.fetchrow(
                """
                INSERT INTO prompt_versions
                    (org_id, stage, agent_role, version, system_prompt,
                     change_summary, is_active, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, org_id, stage, agent_role, version, system_prompt,
                          change_summary, is_active, created_by, created_at
                """,
                org_id,
                stage,
                agent_role,
                next_version,
                system_prompt,
                change_summary,
                activate,
                created_by,
            )

        version = self._row_to_version(row)
        log.info(
            "prompt version created",
            org_id=org_id,
            stage=stage,
            version=next_version,
            activated=activate,
        )
        return version

    async def activate_version(
        self, version_id: str, *, org_id: str
    ) -> bool:
        """Activate a specific version, deactivating the current active one.

        Returns True if the version was found and activated.
        """
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            # Get the version to find its stage
            row = await conn.fetchrow(
                """
                SELECT stage FROM prompt_versions
                WHERE id = $1::uuid AND org_id = $2
                """,
                version_id,
                org_id,
            )
            if row is None:
                return False

            stage = row["stage"]

            # Deactivate current active version for this stage
            await conn.execute(
                """
                UPDATE prompt_versions SET is_active = FALSE
                WHERE org_id = $1 AND stage = $2 AND is_active = TRUE
                """,
                org_id,
                stage,
            )

            # Activate the requested version
            result = await conn.execute(
                """
                UPDATE prompt_versions SET is_active = TRUE
                WHERE id = $1::uuid AND org_id = $2
                """,
                version_id,
                org_id,
            )

        return result.endswith("1")

    async def get_version(
        self, version_id: str, *, org_id: str
    ) -> PromptVersion | None:
        """Fetch a single prompt version by ID."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, org_id, stage, agent_role, version, system_prompt,
                       change_summary, is_active, created_by, created_at
                FROM prompt_versions
                WHERE id = $1::uuid AND org_id = $2
                """,
                version_id,
                org_id,
            )

        if row is None:
            return None
        return self._row_to_version(row)

    async def get_version_history(
        self,
        *,
        org_id: str,
        stage: int,
        limit: int = 20,
        offset: int = 0,
    ) -> list[PromptVersion]:
        """List all prompt versions for an org/stage, newest first."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, org_id, stage, agent_role, version, system_prompt,
                       change_summary, is_active, created_by, created_at
                FROM prompt_versions
                WHERE org_id = $1 AND stage = $2
                ORDER BY version DESC
                LIMIT $3 OFFSET $4
                """,
                org_id,
                stage,
                limit,
                offset,
            )

        return [self._row_to_version(r) for r in rows]

    # ------------------------------------------------------------------
    # Evaluation recording
    # ------------------------------------------------------------------

    async def record_evaluation(
        self,
        *,
        org_id: str,
        prompt_version_id: str,
        pipeline_id: str,
        stage: int,
        agent_role: str,
        verdict: str | None = None,
        attempts: int = 1,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
        error: str | None = None,
    ) -> str:
        """Record a prompt evaluation result. Returns the evaluation UUID."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO prompt_evaluations
                    (org_id, prompt_version_id, pipeline_id, stage,
                     agent_role, verdict, attempts, cost_usd,
                     duration_seconds, error)
                VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                org_id,
                prompt_version_id,
                pipeline_id,
                stage,
                agent_role,
                verdict,
                attempts,
                cost_usd,
                duration_seconds,
                error,
            )

        eval_id = str(row["id"])
        log.info(
            "prompt evaluation recorded",
            eval_id=eval_id,
            prompt_version_id=prompt_version_id,
            pipeline_id=pipeline_id,
            verdict=verdict,
        )
        return eval_id

    # ------------------------------------------------------------------
    # Stats & comparison
    # ------------------------------------------------------------------

    async def get_version_stats(
        self, version_id: str, *, org_id: str
    ) -> PromptVersionStats | None:
        """Compute aggregated performance stats for a prompt version."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    COUNT(*) FILTER (WHERE verdict = 'approved')
                        AS approved_count,
                    COALESCE(AVG(cost_usd), 0) AS avg_cost,
                    COALESCE(AVG(duration_seconds), 0) AS avg_duration,
                    COALESCE(AVG(attempts), 0) AS avg_attempts,
                    COUNT(*) FILTER (WHERE error IS NOT NULL)
                        AS error_count
                FROM prompt_evaluations
                WHERE prompt_version_id = $1::uuid AND org_id = $2
                """,
                version_id,
                org_id,
            )

        if row is None or row["total_runs"] == 0:
            return None

        total = row["total_runs"]
        approved = row["approved_count"]
        return PromptVersionStats(
            version_id=version_id,
            total_runs=total,
            approval_rate=round(approved / total, 4) if total > 0 else 0.0,
            avg_cost_usd=round(float(row["avg_cost"]), 4),
            avg_duration_seconds=round(float(row["avg_duration"]), 2),
            avg_attempts=round(float(row["avg_attempts"]), 2),
            error_count=row["error_count"],
        )

    async def compare_versions(
        self,
        version_id_a: str,
        version_id_b: str,
        *,
        org_id: str,
    ) -> dict[str, Any]:
        """Compare stats of two prompt versions side-by-side."""
        stats_a = await self.get_version_stats(version_id_a, org_id=org_id)
        stats_b = await self.get_version_stats(version_id_b, org_id=org_id)

        ver_a = await self.get_version(version_id_a, org_id=org_id)
        ver_b = await self.get_version(version_id_b, org_id=org_id)

        def _stats_dict(stats: PromptVersionStats | None) -> dict[str, Any]:
            if stats is None:
                return {"total_runs": 0, "approval_rate": 0.0}
            return {
                "total_runs": stats.total_runs,
                "approval_rate": stats.approval_rate,
                "avg_cost_usd": stats.avg_cost_usd,
                "avg_duration_seconds": stats.avg_duration_seconds,
                "avg_attempts": stats.avg_attempts,
                "error_count": stats.error_count,
            }

        def _version_summary(ver: PromptVersion | None) -> dict[str, Any]:
            if ver is None:
                return {}
            return {
                "version": ver.version,
                "change_summary": ver.change_summary,
                "is_active": ver.is_active,
                "prompt_hash": hashlib.sha256(
                    ver.system_prompt.encode()
                ).hexdigest()[:12],
            }

        return {
            "version_a": {
                **_version_summary(ver_a),
                "stats": _stats_dict(stats_a),
            },
            "version_b": {
                **_version_summary(ver_b),
                "stats": _stats_dict(stats_b),
            },
        }

    # ------------------------------------------------------------------
    # Prompt resolution (used at agent execution time)
    # ------------------------------------------------------------------

    async def resolve_prompt(
        self, *, org_id: str, stage: int, default_prompt: str
    ) -> tuple[str, str | None]:
        """Return (system_prompt, version_id) for the given org/stage.

        If the org has an active custom prompt for this stage, returns it
        along with its version_id. Otherwise returns the default prompt
        with version_id=None.
        """
        try:
            active = await self.get_active_prompt(org_id=org_id, stage=stage)
            if active is not None:
                return active.system_prompt, active.id
        except Exception as exc:
            log.debug("prompt resolution fallback to default", error=str(exc))

        return default_prompt, None

    async def get_version_stats_history(
        self, version_id: str, *, org_id: str, days: int = 30
    ) -> list[dict]:
        """Daily aggregated stats for a prompt version over the last N days."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    DATE(created_at) AS date,
                    COUNT(*) FILTER (WHERE verdict = 'approved') AS approved,
                    COUNT(*) AS total,
                    COALESCE(AVG(cost_usd), 0) AS avg_cost
                FROM prompt_evaluations
                WHERE prompt_version_id = $1::uuid
                  AND org_id = $2
                  AND created_at >= now() - make_interval(days => $3)
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at)
                """,
                version_id,
                org_id,
                days,
            )

        return [
            {
                "date": str(row["date"]),
                "approval_rate": round(
                    row["approved"] / row["total"], 4
                )
                if row["total"] > 0
                else 0.0,
                "avg_cost_usd": round(float(row["avg_cost"]), 4),
                "run_count": row["total"],
            }
            for row in rows
        ]

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_version(row) -> PromptVersion:
        return PromptVersion(
            id=str(row["id"]),
            org_id=row["org_id"],
            stage=row["stage"],
            agent_role=row["agent_role"],
            version=row["version"],
            system_prompt=row["system_prompt"],
            change_summary=row["change_summary"],
            is_active=row["is_active"],
            created_by=row["created_by"],
            created_at=row.get("created_at"),
        )
