"""Prompt version management API — version CRUD, activation, stats, comparison, test-run.

Endpoints:
    GET    /api/prompts/versions              — list versions for a stage
    POST   /api/prompts/versions              — create a new version
    GET    /api/prompts/versions/{id}         — get a single version
    PUT    /api/prompts/versions/{id}/activate — activate a version
    GET    /api/prompts/versions/{id}/stats    — get version performance stats
    GET    /api/prompts/versions/{id}/stats/history — daily stats time-series
    POST   /api/prompts/compare               — compare two versions
    GET    /api/prompts/defaults              — list default (built-in) prompts
    POST   /api/prompts/test                  — test a prompt against sample input
    GET    /api/pipelines/{id}/summary        — pipeline completion summary
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.middleware import get_current_user
from auth.types import ForgeUser

log = structlog.get_logger().bind(component="api.prompts")

prompts_router = APIRouter(prefix="/api/prompts", tags=["prompts"])
pipeline_router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])

# ---------------------------------------------------------------------------
# Shared registry instance (lazy)
# ---------------------------------------------------------------------------

_registry = None


def _get_registry():
    global _registry  # noqa: PLW0603
    if _registry is None:
        from agents.prompts.registry import PromptRegistry

        _registry = PromptRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateVersionRequest(BaseModel):
    stage: int
    system_prompt: str
    change_summary: str = ""
    activate: bool = False


class CompareRequest(BaseModel):
    version_a: str
    version_b: str


class VersionResponse(BaseModel):
    id: str
    org_id: str
    stage: int
    agent_role: str
    version: int
    system_prompt: str
    change_summary: str
    is_active: bool
    created_by: str
    created_at: str | None = None
    prompt_hash: str = ""


def _version_to_response(ver) -> dict[str, Any]:
    return {
        "id": ver.id,
        "org_id": ver.org_id,
        "stage": ver.stage,
        "agent_role": ver.agent_role,
        "version": ver.version,
        "system_prompt": ver.system_prompt,
        "change_summary": ver.change_summary,
        "is_active": ver.is_active,
        "created_by": ver.created_by,
        "created_at": (
            ver.created_at.isoformat() if ver.created_at else None
        ),
        "prompt_hash": hashlib.sha256(
            ver.system_prompt.encode()
        ).hexdigest()[:12],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@prompts_router.get("/versions")
async def list_versions(
    stage: int = Query(..., ge=1, le=7),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: ForgeUser = Depends(get_current_user),
):
    """List prompt versions for a stage, newest first."""
    registry = _get_registry()
    versions = await registry.get_version_history(
        org_id=user.org_id,
        stage=stage,
        limit=limit,
        offset=offset,
    )
    return [_version_to_response(v) for v in versions]


@prompts_router.post("/versions")
async def create_version(
    req: CreateVersionRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Create a new prompt version for a stage."""
    if not 1 <= req.stage <= 7:
        raise HTTPException(status_code=400, detail="Stage must be 1-7")
    if not req.system_prompt.strip():
        raise HTTPException(status_code=400, detail="system_prompt is required")

    registry = _get_registry()
    version = await registry.create_version(
        org_id=user.org_id,
        stage=req.stage,
        system_prompt=req.system_prompt,
        change_summary=req.change_summary,
        created_by=user.user_id,
        activate=req.activate,
    )
    return _version_to_response(version)


@prompts_router.get("/versions/{version_id}")
async def get_version(
    version_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Get a single prompt version by ID."""
    registry = _get_registry()
    version = await registry.get_version(version_id, org_id=user.org_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return _version_to_response(version)


@prompts_router.put("/versions/{version_id}/activate")
async def activate_version(
    version_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Activate a prompt version, deactivating any previously active one."""
    registry = _get_registry()
    activated = await registry.activate_version(version_id, org_id=user.org_id)
    if not activated:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"activated": True, "version_id": version_id}


@prompts_router.get("/versions/{version_id}/stats")
async def get_version_stats(
    version_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Get aggregated performance stats for a prompt version."""
    registry = _get_registry()
    stats = await registry.get_version_stats(version_id, org_id=user.org_id)
    if stats is None:
        return {
            "version_id": version_id,
            "total_runs": 0,
            "approval_rate": 0.0,
            "avg_cost_usd": 0.0,
            "avg_duration_seconds": 0.0,
            "avg_attempts": 0.0,
            "error_count": 0,
        }
    return {
        "version_id": stats.version_id,
        "total_runs": stats.total_runs,
        "approval_rate": stats.approval_rate,
        "avg_cost_usd": stats.avg_cost_usd,
        "avg_duration_seconds": stats.avg_duration_seconds,
        "avg_attempts": stats.avg_attempts,
        "error_count": stats.error_count,
    }


@prompts_router.post("/compare")
async def compare_versions(
    req: CompareRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Compare performance stats of two prompt versions."""
    registry = _get_registry()
    return await registry.compare_versions(
        req.version_a,
        req.version_b,
        org_id=user.org_id,
    )


@prompts_router.get("/defaults")
async def list_defaults(
    user: ForgeUser = Depends(get_current_user),
):
    """List built-in default prompts with their hashes.

    Useful for seeing what the baseline is before creating custom versions.
    """
    from agents import PROMPTS_BY_STAGE
    from agents.prompts.registry import STAGE_ROLES

    defaults = []
    for stage, prompts in PROMPTS_BY_STAGE.items():
        prompt_text = prompts["system"]
        defaults.append({
            "stage": stage,
            "agent_role": STAGE_ROLES.get(stage, ""),
            "prompt_hash": hashlib.sha256(
                prompt_text.encode()
            ).hexdigest()[:12],
            "prompt_length": len(prompt_text),
            "preview": prompt_text[:200] + ("..." if len(prompt_text) > 200 else ""),
        })
    return defaults


# ---------------------------------------------------------------------------
# Stats history
# ---------------------------------------------------------------------------


@prompts_router.get("/versions/{version_id}/stats/history")
async def get_version_stats_history(
    version_id: str,
    days: int = Query(30, ge=1, le=365),
    user: ForgeUser = Depends(get_current_user),
):
    """Daily aggregated stats time-series for a prompt version."""
    registry = _get_registry()
    return await registry.get_version_stats_history(
        version_id, org_id=user.org_id, days=days,
    )


# ---------------------------------------------------------------------------
# Test-run endpoint
# ---------------------------------------------------------------------------

# Stage → Pydantic output model
_STAGE_MODELS: dict[int, type] | None = None


def _get_stage_models() -> dict[int, type]:
    global _STAGE_MODELS  # noqa: PLW0603
    if _STAGE_MODELS is None:
        from contracts.schemas import (
            CodeArtifact,
            CTODecision,
            EnrichedSpec,
            PRDBoard,
            ProductSpec,
            QAReview,
            TechSpec,
        )

        _STAGE_MODELS = {
            1: ProductSpec,
            2: EnrichedSpec,
            3: TechSpec,
            4: PRDBoard,
            5: CodeArtifact,
            6: QAReview,
            7: CTODecision,
        }
    return _STAGE_MODELS


# Lightweight sample inputs so users can test prompts without a real pipeline
_SAMPLE_INPUTS: dict[int, str] = {
    1: "Build a simple todo app with user authentication, task CRUD, and due dates.",
    2: "Product: Todo App\nFeatures: user auth, task CRUD, due dates, notifications.",
    3: "Product: Todo App\nResearch: React+Node popular stack. Competitors: Todoist, TickTick.",
    4: "Architecture: React SPA, Node/Express API, PostgreSQL. 3 services.",
    5: "Ticket: Implement POST /api/tasks endpoint with validation and DB persistence.",
    6: "Code: Express route handler for POST /api/tasks with Zod validation, Prisma ORM.",
    7: "QA: All tests pass. Coverage 87%. No critical issues. Minor: add rate limiting.",
}


class TestPromptRequest(BaseModel):
    stage: int
    system_prompt: str
    sample_input: str | None = None


@prompts_router.post("/test")
async def test_prompt(
    req: TestPromptRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Run an agent with a given prompt against sample input (dry-run)."""
    if not 1 <= req.stage <= 7:
        raise HTTPException(status_code=400, detail="Stage must be 1-7")

    from agents.langgraph_runner import run_agent

    stage_models = _get_stage_models()
    output_model = stage_models[req.stage]
    sample_input = req.sample_input or _SAMPLE_INPUTS.get(req.stage, "")

    start = time.monotonic()
    try:
        output, cost = await run_agent(
            system_prompt=req.system_prompt,
            human_prompt=sample_input,
            output_model=output_model,
        )
        duration = round(time.monotonic() - start, 2)
        return {
            "output": output,
            "cost_usd": round(cost, 6),
            "duration_seconds": duration,
            "error": None,
        }
    except Exception as exc:
        duration = round(time.monotonic() - start, 2)
        log.warning("prompt test-run failed", error=str(exc)[:300])
        return {
            "output": None,
            "cost_usd": 0.0,
            "duration_seconds": duration,
            "error": str(exc)[:500],
        }


# ---------------------------------------------------------------------------
# Pipeline summary endpoint
# ---------------------------------------------------------------------------


@pipeline_router.get("/{pipeline_id}/summary")
async def get_pipeline_summary(
    pipeline_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Aggregated cost/duration/lesson summary for a completed pipeline."""
    registry = _get_registry()
    pool = await registry._ensure_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT agent_role, verdict, attempts, cost_usd,
                   duration_seconds, error
            FROM prompt_evaluations
            WHERE pipeline_id = $1 AND org_id = $2
            ORDER BY stage
            """,
            pipeline_id,
            user.org_id,
        )

    if not rows:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    total_cost = 0.0
    total_duration = 0.0
    per_agent: dict[str, dict[str, Any]] = {}

    for row in rows:
        role = row["agent_role"]
        cost = float(row["cost_usd"])
        dur = float(row["duration_seconds"])
        total_cost += cost
        total_duration += dur

        if role not in per_agent:
            per_agent[role] = {
                "cost_usd": 0.0,
                "duration_seconds": 0.0,
                "first_pass": True,
                "attempts": 0,
                "lessons_applied": 0,
            }
        entry = per_agent[role]
        entry["cost_usd"] += cost
        entry["duration_seconds"] += dur
        entry["attempts"] = max(entry["attempts"], row["attempts"])
        if row["attempts"] > 1:
            entry["first_pass"] = False

    # Round values
    for entry in per_agent.values():
        entry["cost_usd"] = round(entry["cost_usd"], 4)
        entry["duration_seconds"] = round(entry["duration_seconds"], 2)

    return {
        "pipeline_id": pipeline_id,
        "total_cost_usd": round(total_cost, 4),
        "total_duration_seconds": round(total_duration, 2),
        "per_agent": per_agent,
        "lessons_applied": [],
    }
