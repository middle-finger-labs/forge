"""PM agent — wires Stage 4 prompts into the LangGraph runner.

Produces a validated PRDBoard from a TechSpec and EnrichedSpec.

Usage::

    from agents.pm_agent import run_pm_agent

    prd_board, cost = await run_pm_agent(tech_spec_dict, enriched_spec_dict)
"""

from __future__ import annotations

import json

import structlog

from agents.langgraph_runner import run_agent
from agents.stage_4_pm import HUMAN_PROMPT_TEMPLATE, SYSTEM_PROMPT
from contracts.schemas import PRDBoard

log = structlog.get_logger().bind(component="pm_agent")


async def run_pm_agent(
    tech_spec: dict,
    enriched_spec: dict,
    *,
    model: str | None = None,
    max_retries: int = 3,
    org_id: str = "",
) -> tuple[dict | None, float]:
    """Run the PM agent to produce a PRDBoard.

    Parameters
    ----------
    tech_spec:
        Dictionary representation of a validated TechSpec.
    enriched_spec:
        Dictionary representation of a validated EnrichedSpec.
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts.
    org_id:
        Org ID for prompt version resolution.

    Returns
    -------
    tuple[dict | None, float]
        (Validated PRDBoard dict or None on failure, cost in USD.)
    """

    # Resolve prompt (org-specific override or default)
    system_prompt = SYSTEM_PROMPT
    try:
        from agents.prompts.evaluation import resolve_stage_prompt

        system_prompt, _ = await resolve_stage_prompt(
            org_id=org_id, stage=4, default_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        log.debug("prompt resolution skipped", error=str(exc))

    product_name = enriched_spec.get("original_spec", {}).get("product_name", "unknown")

    memory_context = ""
    try:
        from memory.semantic_memory import get_relevant_context

        memory_context = await get_relevant_context(
            "pm",
            f"Decompose tech spec into implementation tickets for: {product_name}",
        )
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    human_prompt = HUMAN_PROMPT_TEMPLATE.format(
        tech_spec_json=json.dumps(tech_spec, indent=2),
        enriched_spec_json=json.dumps(enriched_spec, indent=2),
    )

    return await run_agent(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        output_model=PRDBoard,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
    )


# ---------------------------------------------------------------------------
# Elastic decomposition (sketch → parallel detail → assembly)
# ---------------------------------------------------------------------------


async def run_pm_agent_elastic(
    tech_spec: dict,
    enriched_spec: dict,
    *,
    pipeline_id: str = "",
    model: str | None = None,
    max_retries: int = 3,
) -> tuple[dict | None, float]:
    """Three-phase elastic decomposition with automatic fallback.

    1. **Sketch** — one LLM call producing a lightweight outline
    2. **Detail** — parallel LLM calls (semaphore=4) enriching each ticket
    3. **Assembly** — merge sketch + details into a full PRDBoard

    Falls back to :func:`run_pm_agent` if the sketch phase fails.

    Parameters
    ----------
    tech_spec:
        Dictionary representation of a validated TechSpec.
    enriched_spec:
        Dictionary representation of a validated EnrichedSpec.
    pipeline_id:
        Pipeline ID for streaming log events.
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts per LLM call.

    Returns
    -------
    tuple[dict | None, float]
        (Validated PRDBoard dict or None on failure, cost in USD.)
    """
    import asyncio

    from agents.stage_4_pm_elastic import (
        DETAIL_HUMAN_PROMPT_TEMPLATE,
        DETAIL_SYSTEM_PROMPT,
        SKETCH_HUMAN_PROMPT_TEMPLATE,
        SKETCH_SYSTEM_PROMPT,
    )
    from contracts.schemas import PRDBoard, PRDBoardSketch, TicketDetail

    total_cost = 0.0
    product_name = enriched_spec.get("original_spec", {}).get("product_name", "unknown")

    memory_context = ""
    try:
        from memory.semantic_memory import get_relevant_context

        memory_context = await get_relevant_context(
            "pm",
            f"Decompose tech spec into implementation tickets for: {product_name}",
        )
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    # Helper: emit a PM-phase streaming event (best-effort)
    async def _emit(event_type: str, payload: dict | None = None) -> None:
        if not pipeline_id:
            return
        try:
            from memory.agent_log import stream_agent_log

            await stream_agent_log(
                pipeline_id,
                event_type,
                agent_role="pm",
                stage="task_decomposition",
                payload=payload or {},
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Phase 1: Sketch
    # ------------------------------------------------------------------
    await _emit("pm.sketch_started")
    log.info("elastic decomposition: sketch phase", product=product_name)

    sketch_human = SKETCH_HUMAN_PROMPT_TEMPLATE.format(
        tech_spec_json=json.dumps(tech_spec, indent=2),
        enriched_spec_json=json.dumps(enriched_spec, indent=2),
    )

    sketch_result, sketch_cost = await run_agent(
        system_prompt=SKETCH_SYSTEM_PROMPT,
        human_prompt=sketch_human,
        output_model=PRDBoardSketch,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
    )
    total_cost += sketch_cost

    if sketch_result is None:
        log.warning("elastic decomposition: sketch failed, falling back to monolithic")
        return await run_pm_agent(tech_spec, enriched_spec, model=model, max_retries=max_retries)

    tickets_sketch = sketch_result.get("tickets", [])
    await _emit("pm.sketch_completed", {"ticket_count": len(tickets_sketch)})
    log.info(
        "elastic decomposition: sketch complete",
        ticket_count=len(tickets_sketch),
        cost_usd=round(sketch_cost, 4),
    )

    # ------------------------------------------------------------------
    # Phase 2: Detail (parallel, bounded concurrency)
    # ------------------------------------------------------------------
    sem = asyncio.Semaphore(4)
    detail_map: dict[str, dict] = {}

    async def _detail_one(ticket: dict) -> None:
        async with sem:
            tk = ticket["ticket_key"]
            await _emit("pm.detail_started", {"ticket_key": tk})

            detail_human = DETAIL_HUMAN_PROMPT_TEMPLATE.format(
                ticket_key=tk,
                title=ticket.get("title", ""),
                ticket_type=ticket.get("ticket_type", ""),
                priority=ticket.get("priority", ""),
                files_owned=", ".join(ticket.get("files_owned", [])),
                dependencies=", ".join(ticket.get("dependencies", [])),
                tech_spec_json=json.dumps(tech_spec, indent=2),
            )

            result, cost = await run_agent(
                system_prompt=DETAIL_SYSTEM_PROMPT,
                human_prompt=detail_human,
                output_model=TicketDetail,
                model=model,
                max_retries=max_retries,
            )
            nonlocal total_cost
            total_cost += cost

            if result is not None:
                detail_map[tk] = result
                await _emit("pm.detail_completed", {
                    "ticket_key": tk,
                    "story_points": result.get("story_points"),
                })
            else:
                log.warning("elastic decomposition: detail failed", ticket_key=tk)

    await asyncio.gather(*[_detail_one(t) for t in tickets_sketch])

    # ------------------------------------------------------------------
    # Phase 3: Assembly
    # ------------------------------------------------------------------
    assembled_tickets = []
    for sketch_ticket in tickets_sketch:
        tk = sketch_ticket["ticket_key"]
        detail = detail_map.get(tk, {})
        assembled_tickets.append({
            "ticket_key": tk,
            "title": sketch_ticket.get("title", ""),
            "ticket_type": sketch_ticket.get("ticket_type", "feature"),
            "priority": sketch_ticket.get("priority", "medium"),
            "story_points": detail.get("story_points", 3),
            "description": detail.get("description", sketch_ticket.get("title", "")),
            "acceptance_criteria": detail.get("acceptance_criteria", ["Implemented as described"]),
            "files_owned": sketch_ticket.get("files_owned", []),
            "dependencies": sketch_ticket.get("dependencies", []),
            "user_story_refs": sketch_ticket.get("user_story_refs", []),
            "status": "backlog",
        })

    board = {
        "board_id": sketch_result["board_id"],
        "tickets": assembled_tickets,
        "execution_order": sketch_result["execution_order"],
        "critical_path": sketch_result.get("critical_path", []),
    }

    # Validate the assembled board through the full PRDBoard schema
    try:
        validated = PRDBoard.model_validate(board)
        board = validated.model_dump()
    except Exception as exc:
        log.warning(
            "elastic decomposition: assembly validation failed, falling back",
            error=str(exc)[:300],
        )
        return await run_pm_agent(tech_spec, enriched_spec, model=model, max_retries=max_retries)

    # Run existing optimisation and validation utilities
    try:
        from agents.dependency_analyzer import optimize_execution_order, validate_execution_order

        board["execution_order"] = optimize_execution_order(board)
        validate_execution_order(board)
    except Exception as exc:
        log.warning("elastic decomposition: order optimisation failed", error=str(exc)[:200])

    await _emit("pm.decomposition_complete", {
        "ticket_count": len(assembled_tickets),
        "group_count": len(board.get("execution_order", [])),
        "cost_usd": round(total_cost, 4),
    })
    log.info(
        "elastic decomposition: complete",
        ticket_count=len(assembled_tickets),
        group_count=len(board.get("execution_order", [])),
        cost_usd=round(total_cost, 4),
    )

    return board, total_cost


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    TEST_TECH_SPEC = {
        "spec_id": "TECH-001",
        "services": [
            {
                "name": "taskflow-api",
                "responsibility": "REST API for task management",
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/api/v1/tasks",
                        "description": "Create a new task",
                        "request_body": "CreateTaskInput",
                        "response_model": "Task",
                        "auth_required": True,
                    },
                    {
                        "method": "GET",
                        "path": "/api/v1/tasks",
                        "description": "List tasks with filtering",
                        "request_body": None,
                        "response_model": "TaskList",
                        "auth_required": True,
                    },
                    {
                        "method": "PATCH",
                        "path": "/api/v1/tasks/{id}/status",
                        "description": "Update task status (drag between columns)",
                        "request_body": "UpdateStatusInput",
                        "response_model": "Task",
                        "auth_required": True,
                    },
                ],
                "dependencies": [],
            },
        ],
        "database_models": [
            {
                "name": "Task",
                "table_name": "tasks",
                "columns": {
                    "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
                    "title": "TEXT NOT NULL",
                    "description": "TEXT",
                    "status": "TEXT NOT NULL DEFAULT 'todo'",
                    "assignee_id": "UUID REFERENCES users(id)",
                    "due_date": "DATE",
                    "created_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
                    "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
                },
                "indexes": [
                    "idx_tasks_status ON tasks (status)",
                    "idx_tasks_assignee ON tasks (assignee_id)",
                ],
                "relationships": ["belongs_to: User"],
            },
            {
                "name": "User",
                "table_name": "users",
                "columns": {
                    "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
                    "email": "TEXT NOT NULL UNIQUE",
                    "password_hash": "TEXT NOT NULL",
                    "display_name": "TEXT NOT NULL",
                    "created_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
                },
                "indexes": ["idx_users_email ON users (email)"],
                "relationships": ["has_many: Task"],
            },
        ],
        "api_endpoints": [
            {
                "method": "POST",
                "path": "/api/v1/auth/register",
                "description": "Register a new user",
                "auth_required": False,
            },
            {
                "method": "POST",
                "path": "/api/v1/auth/login",
                "description": "Authenticate and receive JWT",
                "auth_required": False,
            },
            {
                "method": "POST",
                "path": "/api/v1/tasks",
                "description": "Create a new task",
                "auth_required": True,
            },
            {
                "method": "GET",
                "path": "/api/v1/tasks",
                "description": "List tasks",
                "auth_required": True,
            },
        ],
        "tech_stack": {
            "backend": "Node.js + Express + TypeScript",
            "database": "PostgreSQL 16 + Drizzle ORM",
            "auth": "JWT + bcrypt",
            "testing": "Vitest",
        },
        "coding_standards": [
            "All functions must have explicit return types",
            "Use Zod for request validation",
        ],
        "file_structure": {
            "src/features/auth/router.ts": "Auth route handlers",
            "src/features/auth/service.ts": "Auth business logic",
            "src/features/tasks/router.ts": "Task route handlers",
            "src/features/tasks/service.ts": "Task business logic",
            "src/features/tasks/repository.ts": "Task database queries",
            "src/features/tasks/schema.ts": "Task Drizzle schema",
            "src/shared/database/connection.ts": "DB connection setup",
            "src/shared/middleware/auth.ts": "JWT auth middleware",
        },
        "user_story_mapping": {
            "US-001": ["taskflow-api", "tasks/router.ts"],
            "US-002": ["taskflow-api", "tasks/router.ts"],
            "US-003": ["taskflow-api", "tasks/router.ts"],
        },
    }

    TEST_ENRICHED_SPEC = {
        "original_spec": {
            "spec_id": "SPEC-001",
            "product_name": "TaskFlow",
            "product_vision": (
                "A lightweight task management app helping small teams organize, "
                "prioritize, and track work through a clean Kanban interface"
            ),
            "target_users": ["small engineering teams", "project managers"],
            "core_problem": (
                "Small teams waste time juggling spreadsheets and chat to track "
                "who is working on what"
            ),
            "proposed_solution": (
                "A focused web app with boards, lists, and cards that lets teams "
                "create tasks, assign owners, set due dates, and track progress "
                "in real time without enterprise bloat"
            ),
            "user_stories": [
                {
                    "id": "US-001",
                    "persona": "team member",
                    "action": "create and assign tasks",
                    "benefit": "single source of truth for ownership",
                    "acceptance_criteria": ["Can create task with all fields"],
                    "priority": "critical",
                    "dependencies": [],
                },
                {
                    "id": "US-002",
                    "persona": "team member",
                    "action": "drag tasks between Kanban columns",
                    "benefit": "visible progress at a glance",
                    "acceptance_criteria": ["Drag updates status in real time"],
                    "priority": "critical",
                    "dependencies": ["US-001"],
                },
                {
                    "id": "US-003",
                    "persona": "project manager",
                    "action": "view overdue tasks dashboard",
                    "benefit": "identify bottlenecks early",
                    "acceptance_criteria": ["Dashboard shows overdue count"],
                    "priority": "high",
                    "dependencies": ["US-001", "US-002"],
                },
            ],
            "success_metrics": [
                "Team adopts within one week",
                "Task cycle time is measurable",
            ],
            "constraints": ["Single deployable unit", "PostgreSQL required"],
            "out_of_scope": ["mobile app", "Gantt charts"],
            "open_questions": [],
        },
        "research_findings": [
            {
                "topic": "Drag-and-drop libraries",
                "summary": "dnd-kit is the recommended React DnD library.",
                "source": "",
                "relevance": "Needed for Kanban board",
                "confidence": 0.85,
            },
        ],
        "competitors": [
            {
                "name": "Trello",
                "url": "https://trello.com",
                "strengths": ["Simple UX"],
                "weaknesses": ["Limited reporting"],
                "differentiators": ["Power-Ups ecosystem"],
            },
        ],
        "feasibility_notes": "All features achievable with standard web tech.",
        "market_context": "Crowded but room for a fast, simple alternative.",
        "revised_questions": [],
        "recommended_changes": [],
    }

    async def main() -> None:
        """Run the PM agent against sample specs and print results."""
        print("Running PM agent...")
        print("=" * 60)

        result, cost = await run_pm_agent(TEST_TECH_SPEC, TEST_ENRICHED_SPEC)

        print("=" * 60)
        print(f"Cost: ${cost:.4f}")
        print()

        if result is None:
            print("FAILED: Agent did not produce valid output.")
        else:
            print("SUCCESS: Valid PRDBoard produced.")
            tickets = result.get("tickets", [])
            exec_order = result.get("execution_order", [])
            print(f"  Board ID:         {result['board_id']}")
            print(f"  Tickets:          {len(tickets)}")
            for t in tickets:
                deps = ", ".join(t.get("dependencies", [])) or "none"
                print(
                    f"    - {t['ticket_key']} [{t['priority']}] {t['title'][:50]}  (deps: {deps})"
                )
            print(f"  Parallel groups:  {len(exec_order)}")
            for i, group in enumerate(exec_order):
                print(f"    Group {i + 1}: {', '.join(group)}")
            crit = result.get("critical_path", [])
            print(f"  Critical path:    {' -> '.join(crit)}")

    asyncio.run(main())
