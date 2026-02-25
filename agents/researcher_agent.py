"""Researcher agent — wires Stage 2 prompts into the LangGraph runner.

Produces a validated EnrichedSpec from a ProductSpec.

Usage::

    from agents.researcher_agent import run_researcher_agent

    enriched_spec, cost = await run_researcher_agent(product_spec_dict)
"""

from __future__ import annotations

import json

import structlog

from agents.langgraph_runner import run_agent
from agents.stage_2_researcher import HUMAN_PROMPT_TEMPLATE, SYSTEM_PROMPT
from contracts.schemas import EnrichedSpec

log = structlog.get_logger().bind(component="researcher_agent")

# NOTE: Web search tool integration is not yet wired into the LangGraph
# graph.  The researcher relies on LLM training knowledge and is explicitly
# instructed (via the prompt suffix below) to mark findings with low
# confidence when it cannot cite a live source.  When web tools are added,
# remove the _NO_WEB_TOOLS_NOTICE suffix.
_NO_WEB_TOOLS_NOTICE = (
    "\n\nIMPORTANT: You do NOT have access to live web search in this run. "
    "Base your research on your training knowledge. For every finding, "
    "set confidence to 'low' or 'medium' unless you are highly certain. "
    "Clearly note when a claim is based on general knowledge rather than "
    "a verified live source. Prefer directionally-correct analysis over "
    "fabricated citations."
)


async def run_researcher_agent(
    product_spec: dict,
    *,
    model: str | None = None,
    max_retries: int = 3,
    org_id: str = "",
) -> tuple[dict | None, float]:
    """Run the researcher agent to produce an EnrichedSpec.

    Parameters
    ----------
    product_spec:
        Dictionary representation of a validated ProductSpec.
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts.
    org_id:
        Org ID for prompt version resolution.

    Returns
    -------
    tuple[dict | None, float]
        (Validated EnrichedSpec dict or None on failure, cost in USD.)
    """

    # Resolve prompt (org-specific override or default)
    system_prompt = SYSTEM_PROMPT
    try:
        from agents.prompts.evaluation import resolve_stage_prompt

        system_prompt, _ = await resolve_stage_prompt(
            org_id=org_id, stage=2, default_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        log.debug("prompt resolution skipped", error=str(exc))

    product_name = product_spec.get("product_name", "unknown product")

    memory_context = ""
    try:
        from memory.semantic_memory import get_relevant_context

        memory_context = await get_relevant_context(
            "researcher",
            f"Research market and competitors for: {product_name}",
        )
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    spec_json = json.dumps(product_spec, indent=2)
    human_prompt = HUMAN_PROMPT_TEMPLATE.format(product_spec_json=spec_json)
    human_prompt += _NO_WEB_TOOLS_NOTICE

    return await run_agent(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        output_model=EnrichedSpec,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
        agent_role="researcher",
        org_id=org_id or None,
    )


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    TEST_PRODUCT_SPEC = {
        "spec_id": "SPEC-001",
        "product_name": "GigBridge",
        "product_vision": (
            "A platform connecting freelancers with short-term project "
            "opportunities, featuring escrow payments and reputation tracking "
            "to build trust between clients and contractors"
        ),
        "target_users": [
            "freelance developers and designers",
            "small businesses needing short-term help",
        ],
        "core_problem": (
            "Freelancers and clients lack a trustworthy way to transact on "
            "short-term projects without risking non-payment or poor delivery"
        ),
        "proposed_solution": (
            "A marketplace where clients post projects with budgets, freelancers "
            "submit proposals, and the platform holds funds in escrow until "
            "deliverables are approved — with mutual ratings after completion"
        ),
        "user_stories": [
            {
                "id": "US-001",
                "persona": "client",
                "action": "post a project with budget, timeline, and required skills",
                "benefit": "attract qualified freelancers quickly",
                "acceptance_criteria": [
                    "Project creation form validates budget > 0 and deadline in the future",
                    "Published projects appear in search within 5 seconds",
                ],
                "priority": "critical",
                "dependencies": [],
            },
            {
                "id": "US-002",
                "persona": "freelancer",
                "action": "browse and filter projects by skill, budget, and timeline",
                "benefit": "find relevant work without sifting through noise",
                "acceptance_criteria": [
                    "Search returns results filtered by at least 3 criteria",
                    "Results page loads in under 2 seconds",
                ],
                "priority": "critical",
                "dependencies": ["US-001"],
            },
            {
                "id": "US-003",
                "persona": "client",
                "action": "fund escrow when accepting a freelancer's proposal",
                "benefit": "freelancer has confidence they will be paid on delivery",
                "acceptance_criteria": [
                    "Escrow is funded via Stripe and reflected in the dashboard",
                    "Freelancer sees escrow status on their project view",
                ],
                "priority": "critical",
                "dependencies": ["US-001", "US-002"],
            },
        ],
        "success_metrics": [
            "50 completed transactions within first 3 months",
            "Average dispute rate below 5%",
        ],
        "constraints": [
            "Must comply with payment processing regulations",
            "MVP targets US market only",
        ],
        "out_of_scope": ["mobile app", "multi-currency support", "video chat"],
        "open_questions": [
            "What payment processor to integrate with?",
            "How to handle disputes that go beyond simple approve/reject?",
        ],
    }

    async def main() -> None:
        """Run the researcher agent against a sample product spec and print results."""
        print("Running researcher agent...")
        print("=" * 60)

        result, cost = await run_researcher_agent(TEST_PRODUCT_SPEC)

        print("=" * 60)
        print(f"Cost: ${cost:.4f}")
        print()

        if result is None:
            print("FAILED: Agent did not produce valid output.")
        else:
            print("SUCCESS: Valid EnrichedSpec produced.")
            findings = result.get("research_findings", [])
            competitors = result.get("competitors", [])
            print(f"  Research findings: {len(findings)}")
            for f in findings:
                print(f"    - [{f.get('confidence', '?')}] {f['topic']}")
            print(f"  Competitors:       {len(competitors)}")
            for c in competitors:
                print(f"    - {c['name']}")
            print(f"  Feasibility:       {result.get('feasibility_notes', '')[:80]}...")
            print(f"  New questions:     {len(result.get('revised_questions', []))}")
            print(f"  Recommended changes: {len(result.get('recommended_changes', []))}")

    asyncio.run(main())
