"""Architect agent — wires Stage 3 prompts into the LangGraph runner.

Produces a validated TechSpec from an enriched product specification.

Usage::

    from agents.architect_agent import run_architect_agent

    tech_spec, cost = await run_architect_agent(enriched_spec_dict)
"""

from __future__ import annotations

import json

import structlog

from agents.langgraph_runner import run_agent
from agents.stage_3_architect import HUMAN_PROMPT_TEMPLATE, SYSTEM_PROMPT
from contracts.schemas import TechSpec

log = structlog.get_logger().bind(component="architect_agent")


async def run_architect_agent(
    enriched_spec: dict,
    *,
    model: str | None = None,
    max_retries: int = 3,
    org_id: str = "",
) -> tuple[dict | None, float]:
    """Run the architect agent to produce a TechSpec.

    Parameters
    ----------
    enriched_spec:
        Dictionary representation of an EnrichedSpec (product spec + research).
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts.
    org_id:
        Org ID for prompt version resolution.

    Returns
    -------
    tuple[dict | None, float]
        (Validated TechSpec dict or None on failure, cost in USD.)
    """

    # Resolve prompt (org-specific override or default)
    system_prompt = SYSTEM_PROMPT
    try:
        from agents.prompts.evaluation import resolve_stage_prompt

        system_prompt, _ = await resolve_stage_prompt(
            org_id=org_id, stage=3, default_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        log.debug("prompt resolution skipped", error=str(exc))

    product_name = enriched_spec.get("original_spec", {}).get("product_name", "unknown")

    memory_context = ""
    try:
        from memory.semantic_memory import SemanticMemory, get_relevant_context

        # General context for the architect role
        memory_context = await get_relevant_context(
            "architect",
            f"Design technical architecture for: {product_name}",
        )

        # Extra recall for past architecture/tech stack decisions
        mem = SemanticMemory()
        decisions = await mem.recall(
            "architecture tech stack decisions",
            agent_role="architect",
            limit=3,
        )
        if decisions:
            lines = [memory_context] if memory_context else []
            lines.append("<past_architecture_decisions>")
            for d in decisions:
                content = d.get("content", "")
                if content:
                    lines.append(f"- {content}")
            lines.append("</past_architecture_decisions>")
            memory_context = "\n".join(lines)
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    enriched_json = json.dumps(enriched_spec, indent=2)
    human_prompt = HUMAN_PROMPT_TEMPLATE.format(enriched_spec_json=enriched_json)

    return await run_agent(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        output_model=TechSpec,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
    )


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    TEST_ENRICHED_SPEC = {
        "original_spec": {
            "spec_id": "SPEC-001",
            "product_name": "TaskFlow",
            "product_vision": (
                "A lightweight task management application that helps small teams "
                "organize, prioritize, and track work items through a clean web interface"
            ),
            "target_users": ["small engineering teams", "project managers"],
            "core_problem": (
                "Small teams waste time juggling spreadsheets and chat messages "
                "to track who is working on what"
            ),
            "proposed_solution": (
                "A focused web app with boards, lists, and cards that lets teams "
                "create tasks, assign owners, set due dates, and track progress "
                "in real time without the bloat of enterprise project tools"
            ),
            "user_stories": [
                {
                    "id": "US-001",
                    "persona": "team member",
                    "action": "create and assign tasks with titles, descriptions, and due dates",
                    "benefit": "the team has a single source of truth for who owns what",
                    "acceptance_criteria": [
                        "User can create a task with title, description, assignee, and due date",
                        "Tasks appear on the board immediately after creation",
                        "Assignee receives a notification when a task is assigned",
                    ],
                    "priority": "critical",
                    "dependencies": [],
                },
                {
                    "id": "US-002",
                    "persona": "team member",
                    "action": "drag tasks between status columns on a Kanban board",
                    "benefit": "everyone can see work progress at a glance",
                    "acceptance_criteria": [
                        "Board displays columns: To Do, In Progress, In Review, Done",
                        "Tasks can be dragged between columns",
                        "Column counts update in real time",
                    ],
                    "priority": "critical",
                    "dependencies": ["US-001"],
                },
                {
                    "id": "US-003",
                    "persona": "project manager",
                    "action": "view a dashboard showing overdue tasks and team workload",
                    "benefit": "I can identify bottlenecks before they cause delays",
                    "acceptance_criteria": [
                        "Dashboard shows count of overdue tasks per assignee",
                        "Dashboard shows tasks per status column as a bar chart",
                        "Data refreshes automatically every 30 seconds",
                    ],
                    "priority": "high",
                    "dependencies": ["US-001", "US-002"],
                },
            ],
            "success_metrics": [
                "Team adopts the tool within one week of deployment",
                "Average task cycle time visible and measurable",
            ],
            "constraints": [
                "Must run as a single deployable unit (no microservices)",
                "Must support PostgreSQL as the database",
            ],
            "out_of_scope": ["mobile app", "Gantt charts", "time tracking"],
            "open_questions": [],
        },
        "research_findings": [
            {
                "topic": "Real-time updates in task boards",
                "summary": (
                    "Server-Sent Events (SSE) provide a simpler alternative to "
                    "WebSockets for one-way real-time updates. Most modern "
                    "browsers support SSE natively with automatic reconnection."
                ),
                "source": "MDN Web Docs",
                "relevance": "Directly applicable to the Kanban board live updates",
                "confidence": 0.9,
            },
            {
                "topic": "Drag-and-drop libraries",
                "summary": (
                    "dnd-kit is the recommended React drag-and-drop library, "
                    "replacing react-beautiful-dnd which is no longer maintained. "
                    "It supports keyboard accessibility out of the box."
                ),
                "source": "dnd-kit documentation",
                "relevance": "Required for the Kanban board drag interaction",
                "confidence": 0.85,
            },
        ],
        "competitors": [
            {
                "name": "Trello",
                "url": "https://trello.com",
                "strengths": ["Simple UX", "Generous free tier"],
                "weaknesses": ["Limited reporting", "Slow with many cards"],
                "differentiators": ["Power-Ups ecosystem"],
            }
        ],
        "feasibility_notes": (
            "All features are achievable with standard web technologies. "
            "The real-time requirement is the main technical challenge but "
            "SSE keeps it straightforward."
        ),
        "market_context": "Crowded market but room for a simple, fast alternative.",
        "revised_questions": [],
        "recommended_changes": [],
    }

    async def main() -> None:
        """Run the architect agent against a sample enriched spec and print results."""
        print("Running architect agent...")
        print("=" * 60)

        result, cost = await run_architect_agent(TEST_ENRICHED_SPEC)

        print("=" * 60)
        print(f"Cost: ${cost:.4f}")
        print()

        if result is None:
            print("FAILED: Agent did not produce valid output.")
        else:
            print("SUCCESS: Valid TechSpec produced.")
            print(f"  Spec ID:          {result['spec_id']}")
            print(f"  Services:         {len(result['services'])}")
            for svc in result["services"]:
                ep_count = len(svc.get("endpoints", []))
                print(f"    - {svc['name']}: {ep_count} endpoints")
            print(f"  Database models:  {len(result.get('database_models', []))}")
            print(f"  API endpoints:    {len(result.get('api_endpoints', []))}")
            print("  Tech stack:")
            for category, tech in result.get("tech_stack", {}).items():
                print(f"    - {category}: {tech}")
            print(f"  Coding standards: {len(result.get('coding_standards', []))}")
            print(f"  File structure:   {len(result.get('file_structure', {}))} entries")
            print(f"  Story mappings:   {len(result.get('user_story_mapping', {}))}")

    asyncio.run(main())
