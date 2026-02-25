"""CTO intervention agent — resolves conflicts when the pipeline gets stuck.

Invoked on-demand (not a pipeline stage) when the QA loop exceeds its retry
limit, agents disagree, or a health check fails.  Uses the LangGraph runner
with a loose ``CTODecision`` model so the LLM's response is validated but
its shape can vary by intervention type.

Usage::

    from agents.cto_agent import run_cto_agent

    decision, cost = await run_cto_agent(
        trigger_type="conflict_resolution",
        trigger_description="FORGE-3 failed QA review 3 times",
        pipeline_state={...},
        context={"qa_history": [...]},
    )
"""

from __future__ import annotations

import json

import structlog

from agents.langgraph_runner import run_agent
from agents.stage_7_cto import HUMAN_PROMPT_TEMPLATE, SYSTEM_PROMPT
from contracts.schemas import CTODecision

log = structlog.get_logger().bind(component="cto_agent")


def _summarise_pipeline_state(pipeline_state: dict) -> str:
    """Build a human-readable summary of the current pipeline state."""
    stage = pipeline_state.get("current_stage", "unknown")
    cost = pipeline_state.get("total_cost_usd", 0.0)

    # Completed tickets
    code_artifacts = pipeline_state.get("code_artifacts", [])
    completed = [a.get("ticket_key", "?") for a in code_artifacts]

    # Active / failed tickets
    active = pipeline_state.get("active_tickets", [])
    failed = pipeline_state.get("failed_tickets", [])

    # QA status
    qa_reviews = pipeline_state.get("qa_reviews", [])
    approved = [r.get("ticket_id", "?") for r in qa_reviews if r.get("verdict") == "approved"]
    revision = [r.get("ticket_id", "?") for r in qa_reviews if r.get("verdict") == "needs_revision"]

    lines = [
        f"Stage:             {stage}",
        f"Cost so far:       ${cost:.2f}",
        f"Tickets completed: {', '.join(completed) or 'none'}",
        f"Tickets active:    {', '.join(active) or 'none'}",
        f"Tickets failed:    {', '.join(failed) or 'none'}",
        f"QA approved:       {', '.join(approved) or 'none'}",
        f"QA needs revision: {', '.join(revision) or 'none'}",
    ]
    return "\n".join(lines)


async def run_cto_agent(
    trigger_type: str,
    trigger_description: str,
    pipeline_state: dict,
    context: dict,
    *,
    model: str | None = None,
    max_retries: int = 3,
    org_id: str = "",
) -> tuple[dict | None, float]:
    """Invoke the CTO agent for an intervention.

    Parameters
    ----------
    trigger_type:
        One of ``conflict_resolution``, ``spec_ambiguity``,
        ``pipeline_health``, or ``human_query``.
    trigger_description:
        Free-text description of the problem that triggered the
        intervention.
    pipeline_state:
        Snapshot of the current pipeline state dict (from the workflow
        query).
    context:
        Additional context relevant to the intervention — e.g.
        ``{"qa_history": [...], "ticket": {...}}``.
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts.
    org_id:
        Org ID for prompt version resolution.

    Returns
    -------
    tuple[dict | None, float]
        (CTO decision dict or None on failure, cost in USD.)
    """
    # Resolve prompt (org-specific override or default)
    system_prompt = SYSTEM_PROMPT
    try:
        from agents.prompts.evaluation import resolve_stage_prompt

        system_prompt, _ = await resolve_stage_prompt(
            org_id=org_id, stage=7, default_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        log.debug("prompt resolution skipped", error=str(exc))

    memory_context = ""
    try:
        from memory.semantic_memory import get_relevant_context

        memory_context = await get_relevant_context(
            "cto",
            f"CTO intervention for {trigger_type}: {trigger_description[:200]}",
        )
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    current_stage = _summarise_pipeline_state(pipeline_state)
    relevant_context = json.dumps(context, indent=2, default=str)

    human_prompt = HUMAN_PROMPT_TEMPLATE.format(
        trigger_type=trigger_type,
        trigger_description=trigger_description,
        current_stage=current_stage,
        relevant_context=relevant_context,
    )

    return await run_agent(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        output_model=CTODecision,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
    )


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        """Run the CTO agent against a sample conflict scenario and print results."""
        print("Running CTO agent (conflict_resolution)...")
        print("=" * 60)

        decision, cost = await run_cto_agent(
            trigger_type="conflict_resolution",
            trigger_description=(
                "Ticket FORGE-3 has failed QA review 3 consecutive times. "
                "The QA engineer keeps flagging missing error handling in "
                "the /api/v1/pipelines endpoint, but the developer argues "
                "the upstream middleware already handles those cases."
            ),
            pipeline_state={
                "current_stage": "qa_review",
                "total_cost_usd": 2.45,
                "code_artifacts": [
                    {"ticket_key": "FORGE-1"},
                    {"ticket_key": "FORGE-2"},
                    {"ticket_key": "FORGE-3"},
                ],
                "qa_reviews": [
                    {"ticket_id": "FORGE-1", "verdict": "approved"},
                    {"ticket_id": "FORGE-2", "verdict": "approved"},
                    {"ticket_id": "FORGE-3", "verdict": "needs_revision"},
                ],
                "active_tickets": ["FORGE-3"],
                "failed_tickets": [],
            },
            context={
                "qa_history": [
                    {
                        "attempt": 1,
                        "verdict": "needs_revision",
                        "comments": "Missing try/catch around DB calls",
                    },
                    {
                        "attempt": 2,
                        "verdict": "needs_revision",
                        "comments": "Error handler added but returns 500 "
                        "instead of structured error",
                    },
                    {
                        "attempt": 3,
                        "verdict": "needs_revision",
                        "comments": "Structured error added but missing "
                        "input validation on request body",
                    },
                ],
                "ticket": {
                    "ticket_key": "FORGE-3",
                    "title": "Create API endpoint",
                    "files_owned": ["activities/api.py"],
                    "acceptance_criteria": [
                        "Returns 201 with pipeline_id",
                        "Validates request body",
                        "Returns structured errors on failure",
                    ],
                },
            },
        )

        print("=" * 60)
        print(f"Cost: ${cost:.4f}")
        print()

        if decision is None:
            print("FAILED: CTO agent did not produce valid output.")
        else:
            print("SUCCESS: CTO decision produced.")
            print(f"  Type:       {decision.get('intervention_type')}")
            print(f"  Decision:   {decision.get('decision', '')[:80]}")
            print(f"  Rationale:  {decision.get('rationale', '')[:80]}")
            print(f"  Action:     {decision.get('pipeline_action', 'N/A')}")

    asyncio.run(main())
