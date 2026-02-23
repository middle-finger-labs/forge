"""Integration tests for the Forge pipeline workflow.

Uses Temporal's in-memory test server — no Docker required.
Activities that call real LLM agents are mocked so tests run without
an API key.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from activities.pipeline_activities import (
    emit_pipeline_event,
    extract_pipeline_lessons,
    finalize_pipeline_state,
    initialize_pipeline_state,
    run_architecture,
    run_business_analysis,
    run_coding_group,
    run_coding_task,
    run_cto_intervention,
    run_integration_check,
    run_merge,
    run_qa_review,
    run_research,
    run_scaffold_project,
    run_task_decomposition,
    run_validate_execution_order,
    store_agent_memory,
)
from workflows.pipeline import CODING_QUEUE, PIPELINE_QUEUE, ForgePipeline
from workflows.types import (
    ApprovalStatus,
    HumanApproval,
    PipelineInput,
    PipelineStage,
)

# ---------------------------------------------------------------------------
# Mocks for real LLM agents (avoids API calls in tests)
# ---------------------------------------------------------------------------

_MOCK_PRODUCT_SPEC = {
    "spec_id": "SPEC-001",
    "product_name": "TestProject",
    "product_vision": (
        "An intelligent automation platform that streamlines the entire software delivery lifecycle"
    ),
    "target_users": ["engineering teams", "technical leads"],
    "core_problem": (
        "Manual ticket grooming, code review, and deployment coordination is slow and scales poorly"
    ),
    "proposed_solution": (
        "Use LLM-powered agents orchestrated by Temporal to automate "
        "the spec-to-code-to-review pipeline with human oversight gates"
    ),
    "user_stories": [
        {
            "id": "US-001",
            "persona": "engineering lead",
            "action": "submit a product brief and receive a structured spec",
            "benefit": "skip hours of manual spec writing",
            "acceptance_criteria": ["Returns a ProductSpec JSON within 60 seconds"],
            "priority": "critical",
            "dependencies": [],
        },
        {
            "id": "US-002",
            "persona": "developer",
            "action": "receive implementation tickets with file paths",
            "benefit": "start coding immediately without ambiguity",
            "acceptance_criteria": ["Each ticket lists files_owned"],
            "priority": "high",
            "dependencies": ["US-001"],
        },
        {
            "id": "US-003",
            "persona": "CTO",
            "action": "review and approve the spec before engineering begins",
            "benefit": "maintain control over scope and direction",
            "acceptance_criteria": ["Pipeline blocks until approval signal"],
            "priority": "critical",
            "dependencies": [],
        },
    ],
    "success_metrics": [
        "Pipeline completes in under 30 minutes",
        "QA auto-approval rate exceeds 80%",
    ],
    "constraints": ["Must run on a single machine"],
    "out_of_scope": ["CI/CD integration"],
    "open_questions": [],
}

_MOCK_TECH_SPEC = {
    "spec_id": "TECH-001",
    "services": [
        {
            "name": "forge-api",
            "responsibility": "HTTP API gateway for pipeline management",
            "endpoints": [
                {
                    "method": "POST",
                    "path": "/api/v1/pipelines",
                    "description": "Start a new pipeline run",
                    "request_body": "PipelineInput",
                    "response_model": "PipelineState",
                    "auth_required": True,
                },
            ],
            "dependencies": [],
        },
    ],
    "database_models": [
        {
            "name": "PipelineRun",
            "table_name": "pipeline_runs",
            "columns": {
                "id": "UUID PRIMARY KEY",
                "status": "TEXT NOT NULL DEFAULT 'pending'",
            },
            "indexes": ["idx_pipeline_runs_status ON pipeline_runs (status)"],
            "relationships": [],
        },
    ],
    "api_endpoints": [
        {
            "method": "GET",
            "path": "/api/v1/pipelines",
            "description": "List pipelines",
            "auth_required": True,
        },
    ],
    "tech_stack": {"language": "Python 3.12", "framework": "FastAPI"},
    "coding_standards": ["All functions must have type annotations"],
    "file_structure": {"workflows/pipeline.py": "Main Temporal workflow"},
    "user_story_mapping": {"US-001": ["forge-api"]},
}

_MOCK_ENRICHED_SPEC = {
    "original_spec": _MOCK_PRODUCT_SPEC,
    "research_findings": [
        {
            "topic": "Market analysis",
            "summary": "Strong demand for automated pipelines.",
            "source": "",
            "relevance": "Validates product direction",
            "confidence": 0.6,
        },
    ],
    "competitors": [
        {
            "name": "Competitor A",
            "url": "https://example.com",
            "strengths": ["Good UX"],
            "weaknesses": ["No orchestration"],
            "differentiators": ["Our Temporal-based approach"],
        },
    ],
    "feasibility_notes": "Feasible with current LLM capabilities.",
    "market_context": "Growing market for AI dev tools.",
    "revised_questions": [],
    "recommended_changes": [],
}

_MOCK_PRD_BOARD = {
    "board_id": "BOARD-001",
    "tickets": [
        {
            "ticket_key": "FORGE-1",
            "title": "Scaffold project infrastructure",
            "ticket_type": "infrastructure",
            "priority": "critical",
            "story_points": 3,
            "description": "Create project scaffolding and config.",
            "acceptance_criteria": ["docker compose up works"],
            "files_owned": ["pyproject.toml", "docker-compose.yml"],
            "dependencies": [],
            "user_story_refs": ["US-001"],
            "status": "backlog",
        },
        {
            "ticket_key": "FORGE-2",
            "title": "Implement database models",
            "ticket_type": "feature",
            "priority": "high",
            "story_points": 5,
            "description": "Create DB models and repository layer.",
            "acceptance_criteria": ["CRUD operations pass tests"],
            "files_owned": ["activities/db.py"],
            "dependencies": ["FORGE-1"],
            "user_story_refs": ["US-001"],
            "status": "backlog",
        },
        {
            "ticket_key": "FORGE-3",
            "title": "Create API endpoint",
            "ticket_type": "feature",
            "priority": "high",
            "story_points": 5,
            "description": "Implement POST /api/v1/pipelines endpoint.",
            "acceptance_criteria": ["Returns 201 with pipeline_id"],
            "files_owned": ["activities/api.py"],
            "dependencies": ["FORGE-2"],
            "user_story_refs": ["US-001"],
            "status": "backlog",
        },
    ],
    "execution_order": [["FORGE-1"], ["FORGE-2"], ["FORGE-3"]],
    "critical_path": ["FORGE-1", "FORGE-2", "FORGE-3"],
}


def _mock_qa_review(ticket: dict, code_artifact: dict, coding_standards: list[str]):
    """Build a mock QAReview result matching the given ticket."""
    criteria = ticket.get("acceptance_criteria", [])
    return {
        "ticket_key": ticket.get("ticket_key", "FORGE-0"),
        "verdict": "approved",
        "criteria_compliance": {c: True for c in criteria},
        "code_quality_score": 8,
        "comments": [
            {
                "file_path": "mock_file.py",
                "line": None,
                "severity": "info",
                "comment": "Clean implementation",
            },
        ],
        "security_concerns": [],
        "performance_concerns": [],
        "revision_instructions": [],
    }


@pytest.fixture(autouse=True)
def _mock_llm_agents(monkeypatch):
    """Patch all real LLM agents so activities return mock data.

    Also sets FORGE_TEST_MODE=1 so the coding and merge activities use
    their built-in mock paths instead of real git worktrees and LLM calls.
    """
    monkeypatch.setenv("FORGE_TEST_MODE", "1")

    ba_mock = AsyncMock(return_value=(_MOCK_PRODUCT_SPEC, 0.03))
    research_mock = AsyncMock(return_value=(_MOCK_ENRICHED_SPEC, 0.08))
    arch_mock = AsyncMock(return_value=(_MOCK_TECH_SPEC, 0.12))
    pm_mock = AsyncMock(return_value=(_MOCK_PRD_BOARD, 0.05))

    async def qa_side_effect(ticket, code_artifact, coding_standards):
        return (_mock_qa_review(ticket, code_artifact, coding_standards), 0.06)

    qa_mock = AsyncMock(side_effect=qa_side_effect)
    with (
        patch("activities.pipeline_activities.run_ba_agent", ba_mock),
        patch("activities.pipeline_activities.run_researcher_agent", research_mock),
        patch("activities.pipeline_activities.run_architect_agent", arch_mock),
        patch("activities.pipeline_activities.run_pm_agent", pm_mock),
        patch("activities.pipeline_activities.run_qa_agent", qa_mock),
    ):
        yield


# Use the real queue names — the workflow hardcodes activity dispatches to
# PIPELINE_QUEUE / CODING_QUEUE, so workers must listen on those exact queues.
PIPELINE_ACTIVITIES = [
    run_business_analysis,
    run_research,
    run_architecture,
    run_task_decomposition,
    run_scaffold_project,
    run_validate_execution_order,
    run_qa_review,
    run_merge,
    run_cto_intervention,
    emit_pipeline_event,
    initialize_pipeline_state,
    finalize_pipeline_state,
    extract_pipeline_lessons,
    store_agent_memory,
]

CODING_ACTIVITIES = [
    run_coding_task,
    run_coding_group,
    run_integration_check,
]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


def _unique_id() -> str:
    return uuid.uuid4().hex[:12]


async def _poll_until(handle, predicate, *, label="condition", max_polls=60, interval=0.3):
    """Poll workflow state until predicate returns True."""
    for _ in range(max_polls):
        try:
            state = await handle.query(ForgePipeline.get_state)
            if predicate(state):
                return state
        except Exception:
            pass
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {label}")


# ---------------------------------------------------------------------------
# Test 1 — Full pipeline success (end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_success(env: WorkflowEnvironment) -> None:
    """Start pipeline, approve both gates, verify completion with all artifacts."""

    async with (
        Worker(
            env.client,
            task_queue=PIPELINE_QUEUE,
            workflows=[ForgePipeline],
            activities=PIPELINE_ACTIVITIES,
        ),
        Worker(
            env.client,
            task_queue=CODING_QUEUE,
            activities=CODING_ACTIVITIES,
        ),
    ):
        pipeline_id = _unique_id()
        wf_id = f"forge-pipeline-{pipeline_id}"

        handle = await env.client.start_workflow(
            ForgePipeline.run,
            PipelineInput(
                pipeline_id=pipeline_id,
                business_spec="Build a task management app with user auth and real-time updates",
                project_name="TaskFlow",
            ),
            id=wf_id,
            task_queue=PIPELINE_QUEUE,
        )

        # Approve BA stage
        await _poll_until(
            handle,
            lambda s: s["pending_approval"] == PipelineStage.BUSINESS_ANALYSIS,
            label="BA approval pending",
        )
        await handle.signal(
            ForgePipeline.human_approval,
            HumanApproval(
                stage=PipelineStage.BUSINESS_ANALYSIS,
                status=ApprovalStatus.APPROVED,
                notes="Looks good",
                approved_by="test-user",
            ),
        )

        # Approve architecture stage
        await _poll_until(
            handle,
            lambda s: s["pending_approval"] == PipelineStage.ARCHITECTURE,
            label="Architecture approval pending",
        )
        await handle.signal(
            ForgePipeline.human_approval,
            HumanApproval(
                stage=PipelineStage.ARCHITECTURE,
                status=ApprovalStatus.APPROVED,
                notes="Architecture approved",
                approved_by="test-user",
            ),
        )

        result = await handle.result()

        # Pipeline completed successfully
        assert result["current_stage"] == PipelineStage.COMPLETE

        # All artifact stages populated
        assert result["product_spec"] is not None
        assert result["enriched_spec"] is not None
        assert result["tech_spec"] is not None
        assert result["prd_board"] is not None

        # Code was produced and reviewed
        assert len(result["code_artifacts"]) > 0
        assert len(result["qa_reviews"]) > 0

        # Cost accumulated from mock activities
        assert result["total_cost_usd"] > 0

        # Not aborted
        assert result["aborted"] is False


# ---------------------------------------------------------------------------
# Test 2 — Human rejection halts pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_rejection_halts_pipeline(env: WorkflowEnvironment) -> None:
    """Rejecting the BA stage should cause the workflow to fail."""

    async with (
        Worker(
            env.client,
            task_queue=PIPELINE_QUEUE,
            workflows=[ForgePipeline],
            activities=PIPELINE_ACTIVITIES,
        ),
        Worker(
            env.client,
            task_queue=CODING_QUEUE,
            activities=CODING_ACTIVITIES,
        ),
    ):
        pipeline_id = _unique_id()
        wf_id = f"forge-pipeline-{pipeline_id}"

        handle = await env.client.start_workflow(
            ForgePipeline.run,
            PipelineInput(
                pipeline_id=pipeline_id,
                business_spec="A vague idea",
                project_name="Rejected",
            ),
            id=wf_id,
            task_queue=PIPELINE_QUEUE,
        )

        # Wait for BA approval request, then reject
        await _poll_until(
            handle,
            lambda s: s["pending_approval"] == PipelineStage.BUSINESS_ANALYSIS,
            label="BA approval pending",
        )
        await handle.signal(
            ForgePipeline.human_approval,
            HumanApproval(
                stage=PipelineStage.BUSINESS_ANALYSIS,
                status=ApprovalStatus.REJECTED,
                notes="Spec is too vague",
                approved_by="test-reviewer",
            ),
        )

        with pytest.raises(WorkflowFailureError) as exc_info:
            await handle.result()

        assert "rejected" in str(exc_info.value.cause).lower()


# ---------------------------------------------------------------------------
# Test 3 — Budget exceeded kills pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exceeded(env: WorkflowEnvironment) -> None:
    """Setting max_cost_usd=0 should trigger the budget kill switch."""

    async with (
        Worker(
            env.client,
            task_queue=PIPELINE_QUEUE,
            workflows=[ForgePipeline],
            activities=PIPELINE_ACTIVITIES,
        ),
        Worker(
            env.client,
            task_queue=CODING_QUEUE,
            activities=CODING_ACTIVITIES,
        ),
    ):
        pipeline_id = _unique_id()
        wf_id = f"forge-pipeline-{pipeline_id}"

        handle = await env.client.start_workflow(
            ForgePipeline.run,
            PipelineInput(
                pipeline_id=pipeline_id,
                business_spec="Build something expensive",
                project_name="Overbudget",
                config_overrides={"max_cost_usd": 0},
            ),
            id=wf_id,
            task_queue=PIPELINE_QUEUE,
        )

        with pytest.raises(WorkflowFailureError) as exc_info:
            await handle.result()

        error_msg = str(exc_info.value.cause).lower()
        assert "budget" in error_msg or "exceeded" in error_msg


# ---------------------------------------------------------------------------
# Test 4 — Typed error: LLMError retried then succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_error_retried_then_succeeds(env: WorkflowEnvironment) -> None:
    """An activity that raises LLMError on the first call should be
    retried by the workflow's _run_stage loop and succeed on the second call."""

    call_count = 0

    async def _ba_side_effect(business_spec):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Internal Server Error 500 from model API")
        return (_MOCK_PRODUCT_SPEC, 0.03)

    ba_mock = AsyncMock(side_effect=_ba_side_effect)

    with patch("activities.pipeline_activities.run_ba_agent", ba_mock):
        async with (
            Worker(
                env.client,
                task_queue=PIPELINE_QUEUE,
                workflows=[ForgePipeline],
                activities=PIPELINE_ACTIVITIES,
            ),
            Worker(
                env.client,
                task_queue=CODING_QUEUE,
                activities=CODING_ACTIVITIES,
            ),
        ):
            pipeline_id = _unique_id()
            wf_id = f"forge-pipeline-{pipeline_id}"

            handle = await env.client.start_workflow(
                ForgePipeline.run,
                PipelineInput(
                    pipeline_id=pipeline_id,
                    business_spec="Build a retryable app",
                    project_name="RetryTest",
                ),
                id=wf_id,
                task_queue=PIPELINE_QUEUE,
            )

            # Approve BA stage
            await _poll_until(
                handle,
                lambda s: s["pending_approval"] == PipelineStage.BUSINESS_ANALYSIS,
                label="BA approval pending",
            )
            await handle.signal(
                ForgePipeline.human_approval,
                HumanApproval(
                    stage=PipelineStage.BUSINESS_ANALYSIS,
                    status=ApprovalStatus.APPROVED,
                    notes="OK",
                    approved_by="test-user",
                ),
            )

            # Approve architecture stage
            await _poll_until(
                handle,
                lambda s: s["pending_approval"] == PipelineStage.ARCHITECTURE,
                label="Architecture approval pending",
            )
            await handle.signal(
                ForgePipeline.human_approval,
                HumanApproval(
                    stage=PipelineStage.ARCHITECTURE,
                    status=ApprovalStatus.APPROVED,
                    notes="Architecture approved",
                    approved_by="test-user",
                ),
            )

            result = await handle.result()

            # Pipeline should succeed after the retry
            assert result["current_stage"] == PipelineStage.COMPLETE
            assert result["product_spec"] is not None
            # BA was called at least twice (first fail + second succeed)
            assert call_count >= 2


# ---------------------------------------------------------------------------
# Test 5 — BudgetExceededError aborts immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exceeded_error_aborts(env: WorkflowEnvironment) -> None:
    """An activity raising BudgetExceededError should cause immediate
    pipeline failure with no retries."""

    async def _ba_budget_exceeded(business_spec):
        raise RuntimeError("Budget exceeded: cost budget limit reached")

    ba_mock = AsyncMock(side_effect=_ba_budget_exceeded)

    with patch("activities.pipeline_activities.run_ba_agent", ba_mock):
        async with (
            Worker(
                env.client,
                task_queue=PIPELINE_QUEUE,
                workflows=[ForgePipeline],
                activities=PIPELINE_ACTIVITIES,
            ),
            Worker(
                env.client,
                task_queue=CODING_QUEUE,
                activities=CODING_ACTIVITIES,
            ),
        ):
            pipeline_id = _unique_id()
            wf_id = f"forge-pipeline-{pipeline_id}"

            handle = await env.client.start_workflow(
                ForgePipeline.run,
                PipelineInput(
                    pipeline_id=pipeline_id,
                    business_spec="Trigger budget error",
                    project_name="BudgetAbort",
                ),
                id=wf_id,
                task_queue=PIPELINE_QUEUE,
            )

            with pytest.raises(WorkflowFailureError):
                await handle.result()

            # BA should only have been called once (no retry)
            assert ba_mock.call_count == 1
