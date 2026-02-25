"""Evaluation recording helpers for prompt version management.

Provides fire-and-forget functions used by pipeline activities to record
how each prompt version performs.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger().bind(component="prompt_evaluation")


async def record_stage_evaluation(
    *,
    org_id: str,
    pipeline_id: str,
    stage: int,
    agent_role: str,
    prompt_version_id: str | None,
    verdict: str | None = None,
    attempts: int = 1,
    cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
    error: str | None = None,
) -> None:
    """Record a prompt evaluation after a stage completes.

    Best-effort — failures are logged but never propagate.
    If *prompt_version_id* is None (using default prompt), this is a no-op.
    """
    if not prompt_version_id:
        return

    try:
        from agents.prompts.registry import PromptRegistry

        registry = PromptRegistry()
        await registry.record_evaluation(
            org_id=org_id,
            prompt_version_id=prompt_version_id,
            pipeline_id=pipeline_id,
            stage=stage,
            agent_role=agent_role,
            verdict=verdict,
            attempts=attempts,
            cost_usd=cost_usd,
            duration_seconds=duration_seconds,
            error=error,
        )
    except Exception as exc:
        log.debug("prompt evaluation recording skipped", error=str(exc))


async def resolve_stage_prompt(
    *, org_id: str, stage: int, default_prompt: str
) -> tuple[str, str | None]:
    """Resolve the system prompt for a stage, returning (prompt, version_id).

    Best-effort — falls back to default_prompt on any error.
    """
    if not org_id:
        return default_prompt, None

    try:
        from agents.prompts.registry import PromptRegistry

        registry = PromptRegistry()
        return await registry.resolve_prompt(
            org_id=org_id, stage=stage, default_prompt=default_prompt,
        )
    except Exception as exc:
        log.debug("prompt resolution fallback to default", error=str(exc))
        return default_prompt, None
