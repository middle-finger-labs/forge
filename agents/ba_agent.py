"""Business Analyst agent — wires Stage 1 prompts into the LangGraph runner.

Produces a validated ProductSpec from a raw business specification.

Usage::

    from agents.ba_agent import run_ba_agent

    product_spec, cost = await run_ba_agent("Build a platform for ...")
"""

from __future__ import annotations

import structlog

from agents.langgraph_runner import run_agent
from agents.stage_1_business_analyst import HUMAN_PROMPT_TEMPLATE, SYSTEM_PROMPT
from contracts.schemas import ProductSpec

log = structlog.get_logger().bind(component="ba_agent")


async def run_ba_agent(
    business_spec: str,
    *,
    model: str | None = None,
    max_retries: int = 3,
    org_id: str = "",
) -> tuple[dict | None, float]:
    """Run the BA agent to produce a ProductSpec.

    Parameters
    ----------
    business_spec:
        Raw business specification text (anything from a Slack thread to a brief).
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts.
    org_id:
        Org ID for prompt version resolution.

    Returns
    -------
    tuple[dict | None, float]
        (Validated ProductSpec dict or None on failure, cost in USD.)
    """

    # Resolve prompt (org-specific override or default)
    system_prompt = SYSTEM_PROMPT
    try:
        from agents.prompts.evaluation import resolve_stage_prompt

        system_prompt, _ = await resolve_stage_prompt(
            org_id=org_id, stage=1, default_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        log.debug("prompt resolution skipped", error=str(exc))

    # Retrieve relevant memories for context
    memory_context = ""
    try:
        from memory.semantic_memory import get_relevant_context

        memory_context = await get_relevant_context(
            "business_analyst",
            f"Analyse business spec and produce product specification: {business_spec[:200]}",
        )
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    human_prompt = HUMAN_PROMPT_TEMPLATE.format(business_spec=business_spec)

    return await run_agent(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        output_model=ProductSpec,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
        agent_role="business_analyst",
        org_id=org_id or None,
    )


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    TEST_BUSINESS_SPEC = (
        "Build a platform for freelancers to find short-term projects, "
        "with escrow payments and reputation tracking. Clients post projects "
        "with budgets and timelines, freelancers submit proposals, and the "
        "platform holds payment in escrow until the client approves the "
        "deliverable. Both sides can rate each other after completion. "
        "The platform takes a 10% service fee on each transaction."
    )

    async def main() -> None:
        """Run the BA agent against a sample business spec and print results."""
        print("Running BA agent...")
        print("=" * 60)

        result, cost = await run_ba_agent(TEST_BUSINESS_SPEC)

        print("=" * 60)
        print(f"Cost: ${cost:.4f}")
        print()

        if result is None:
            print("FAILED: Agent did not produce valid output.")
        else:
            print("SUCCESS: Valid ProductSpec produced.")
            print(f"  Spec ID:         {result['spec_id']}")
            print(f"  Product name:    {result['product_name']}")
            print(f"  Target users:    {', '.join(result['target_users'])}")
            print(f"  User stories:    {len(result['user_stories'])}")
            for story in result["user_stories"]:
                print(f"    - [{story['priority']}] {story['id']}: {story['action'][:60]}")
            print(f"  Success metrics: {len(result['success_metrics'])}")
            print(f"  Constraints:     {len(result.get('constraints', []))}")
            print(f"  Out of scope:    {len(result.get('out_of_scope', []))}")
            print(f"  Open questions:  {len(result.get('open_questions', []))}")

    asyncio.run(main())
