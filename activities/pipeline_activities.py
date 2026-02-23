"""Temporal activity stubs for every pipeline stage.

Each activity returns realistic mock data so the full workflow can be tested
end-to-end without LLM calls or external services.  Replace the mock bodies
with real agent integrations as each stage is implemented.
"""

from __future__ import annotations

import asyncio
import os
import time
import traceback
import uuid

import structlog
from temporalio import activity

from agents.architect_agent import run_architect_agent
from agents.ba_agent import run_ba_agent
from agents.coding_agent import run_coding_agent_task
from agents.cto_agent import run_cto_agent
from agents.dependency_analyzer import (
    apply_ownership_fixes,
    detect_file_ownership_conflicts,
    optimize_execution_order,
    suggest_file_ownership_fixes,
    validate_execution_order,
)
from agents.pm_agent import run_pm_agent, run_pm_agent_elastic
from agents.project_scaffold import scaffold_project
from agents.qa_agent import run_qa_agent
from agents.researcher_agent import run_researcher_agent
from agents.swarm_coordinator import SwarmCoordinator
from agents.worktree_manager import WorktreeManager
from config.errors import (
    AgentTimeoutError,
    BudgetExceededError,
    ContentPolicyError,
    ForgeError,
    GitError,
    LLMError,
    MergeConflictError,
    ValidationError,
    get_error_reporter,
)
from memory import get_state_store, get_working_memory
from memory.observability import set_pipeline_context
from memory.working_memory import BatchEventEmitter
from workflows.types import (
    CodingTaskInput,
    CodingTaskResult,
    GroupTaskInput,
    GroupTaskResult,
    PipelineEvent,
    PipelineStage,
    QATaskInput,
    QATaskResult,
    StageResult,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Error classification & bridging helpers
# ---------------------------------------------------------------------------


def _classify_and_wrap(
    exc: Exception,
    *,
    pipeline_id: str,
    stage: str,
    agent_role: str,
) -> ForgeError:
    """Inspect a raw exception and wrap it in the appropriate ForgeError subclass."""
    msg = str(exc)
    exc_type = type(exc).__name__
    kwargs = {"pipeline_id": pipeline_id, "stage": stage, "agent_role": agent_role}

    msg_lower = msg.lower()

    # Budget
    if "budget" in msg_lower and ("exceed" in msg_lower or "limit" in msg_lower):
        return BudgetExceededError(msg, **kwargs)

    # Content policy
    content_kw = ("content_policy", "content policy", "content filter")
    if any(kw in msg_lower for kw in content_kw):
        return ContentPolicyError(msg, **kwargs)

    # Timeout
    if isinstance(exc, TimeoutError) or "timeout" in exc_type.lower():
        return AgentTimeoutError(msg, **kwargs)

    # Worktree / git errors (detect by type name to avoid import coupling)
    if exc_type in ("WorktreeError", "GitOperationError") or "worktree" in msg_lower:
        if "conflict" in msg_lower or "merge" in msg_lower:
            return MergeConflictError(msg, **kwargs)
        return GitError(msg, **kwargs)

    # Git errors detected by message patterns
    if "fatal:" in msg_lower or "git checkout failed" in msg_lower or "git " in msg_lower and "failed" in msg_lower:
        if "conflict" in msg_lower or "merge" in msg_lower:
            return MergeConflictError(msg, **kwargs)
        return GitError(msg, **kwargs)

    # Rate limit
    if "429" in msg or "rate_limit" in msg_lower or "rate limit" in msg_lower:
        return LLMError(msg, error_category="rate_limit", **kwargs)

    # Server errors (5xx)
    if any(code in msg for code in ("500", "502", "503", "529")):
        return LLMError(msg, error_category="server_error", **kwargs)

    # Validation
    if isinstance(exc, (ValueError, KeyError)) and "validat" in msg_lower:
        return ValidationError(msg, validation_errors=[msg], **kwargs)

    # Default → LLM unknown
    return LLMError(msg, error_category="unknown", **kwargs)


def _raise_as_temporal(error: ForgeError) -> None:
    """Convert a ForgeError into a Temporal ApplicationError and raise it."""
    from temporalio.exceptions import ApplicationError

    raise ApplicationError(
        str(error),
        error.to_dict(),
        type=type(error).__name__,
        non_retryable=not error.is_retryable,
    )


def _get_error_reporter():
    """Return the ErrorReporter singleton."""
    return get_error_reporter()


# ---------------------------------------------------------------------------
# Stage 1 — Business Analysis
# ---------------------------------------------------------------------------


@activity.defn(name="run_business_analysis")
async def run_business_analysis(input: dict) -> StageResult:
    """Analyse a raw business spec and produce a ProductSpec.

    Calls the real LangGraph-based BA agent to produce a validated
    ProductSpec.  Falls back to a failed StageResult on any error.

    Input keys: business_spec (str), project_name (str)
    """

    business_spec = input.get("business_spec", "")
    project_name = input.get("project_name", "")
    pipeline_id = input.get("pipeline_id", "")
    org_id = input.get("org_id", "")
    model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

    set_pipeline_context(pipeline_id=pipeline_id, agent_role="business_analyst", org_id=org_id)

    pipeline_log = log.bind(
        activity="run_business_analysis",
        project_name=project_name,
        model=model,
    )
    pipeline_log.info("starting business analysis (real agent)")
    start = time.monotonic()

    try:
        result, cost = await run_ba_agent(business_spec)
        elapsed = time.monotonic() - start

        if result is not None:
            pipeline_log.info(
                "business analysis complete",
                success=True,
                stories=len(result.get("user_stories", [])),
                cost_usd=round(cost, 4),
                duration_seconds=round(elapsed, 2),
            )
            await _persist_stage(
                input.get("pipeline_id", ""),
                "business_analysis",
                result,
                cost,
                pipeline_log,
            )
            return StageResult(
                stage=PipelineStage.BUSINESS_ANALYSIS,
                success=True,
                artifact=result,
                cost_usd=cost,
                duration_seconds=round(elapsed, 2),
            )

        pipeline_log.warning(
            "business analysis failed — no valid output after retries",
            cost_usd=round(cost, 4),
            duration_seconds=round(elapsed, 2),
        )
        error = ValidationError(
            "BA agent failed to produce valid ProductSpec after retries",
            pipeline_id=pipeline_id,
            stage="business_analysis",
            agent_role="business_analyst",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "business analysis errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="business_analysis",
            agent_role="business_analyst",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Stage 2 — Research
# ---------------------------------------------------------------------------


@activity.defn(name="run_research")
async def run_research(input: dict) -> StageResult:
    """Enrich a ProductSpec with market research and competitor analysis.

    Calls the real LangGraph-based researcher agent to produce a validated
    EnrichedSpec.  Falls back to a failed StageResult on any error.

    Input keys: product_spec (dict)
    """

    product_spec = input.get("product_spec", {})
    spec_id = product_spec.get("spec_id", "")
    pipeline_id = input.get("pipeline_id", "")
    org_id = input.get("org_id", "")
    model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

    set_pipeline_context(pipeline_id=pipeline_id, agent_role="researcher", org_id=org_id)

    pipeline_log = log.bind(
        activity="run_research",
        spec_id=spec_id,
        model=model,
    )
    pipeline_log.info("starting research (real agent)")
    start = time.monotonic()

    try:
        result, cost = await run_researcher_agent(product_spec)
        elapsed = time.monotonic() - start

        if result is not None:
            pipeline_log.info(
                "research complete",
                success=True,
                findings=len(result.get("research_findings", [])),
                competitors=len(result.get("competitors", [])),
                cost_usd=round(cost, 4),
                duration_seconds=round(elapsed, 2),
            )
            await _persist_stage(
                input.get("pipeline_id", ""),
                "research",
                result,
                cost,
                pipeline_log,
            )
            return StageResult(
                stage=PipelineStage.RESEARCH,
                success=True,
                artifact=result,
                cost_usd=cost,
                duration_seconds=round(elapsed, 2),
            )

        pipeline_log.warning(
            "research failed — no valid output after retries",
            cost_usd=round(cost, 4),
            duration_seconds=round(elapsed, 2),
        )
        error = ValidationError(
            "Researcher agent failed to produce valid EnrichedSpec after retries",
            pipeline_id=pipeline_id,
            stage="research",
            agent_role="researcher",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "research errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="research",
            agent_role="researcher",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Stage 3 — Architecture
# ---------------------------------------------------------------------------


@activity.defn(name="run_architecture")
async def run_architecture(input: dict) -> StageResult:
    """Design the technical architecture from an EnrichedSpec.

    Calls the real LangGraph-based architect agent to produce a validated
    TechSpec.  Falls back to a failed StageResult on any error.

    Input keys: enriched_spec (dict)
    """

    enriched_spec = input.get("enriched_spec", {})
    spec_id = enriched_spec.get("original_spec", {}).get("spec_id", "")
    pipeline_id = input.get("pipeline_id", "")
    org_id = input.get("org_id", "")
    model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

    set_pipeline_context(pipeline_id=pipeline_id, agent_role="architect", org_id=org_id)

    pipeline_log = log.bind(
        activity="run_architecture",
        spec_id=spec_id,
        model=model,
    )
    pipeline_log.info("starting architecture design (real agent)")
    start = time.monotonic()

    try:
        result, cost = await run_architect_agent(enriched_spec)
        elapsed = time.monotonic() - start

        if result is not None:
            pipeline_log.info(
                "architecture design complete",
                success=True,
                services=len(result.get("services", [])),
                cost_usd=round(cost, 4),
                duration_seconds=round(elapsed, 2),
            )
            await _persist_stage(
                input.get("pipeline_id", ""),
                "architecture",
                result,
                cost,
                pipeline_log,
            )
            return StageResult(
                stage=PipelineStage.ARCHITECTURE,
                success=True,
                artifact=result,
                cost_usd=cost,
                duration_seconds=round(elapsed, 2),
            )

        pipeline_log.warning(
            "architecture design failed — no valid output after retries",
            cost_usd=round(cost, 4),
            duration_seconds=round(elapsed, 2),
        )
        error = ValidationError(
            "Architect agent failed to produce valid TechSpec after retries",
            pipeline_id=pipeline_id,
            stage="architecture",
            agent_role="architect",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "architecture design errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="architecture",
            agent_role="architect",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Stage 4 — Task Decomposition
# ---------------------------------------------------------------------------


@activity.defn(name="run_task_decomposition")
async def run_task_decomposition(input: dict) -> StageResult:
    """Decompose a TechSpec into implementation tickets (PRDBoard).

    Calls the real LangGraph-based PM agent to produce a validated
    PRDBoard.  Falls back to a failed StageResult on any error.

    Input keys: tech_spec (dict), enriched_spec (dict)
    """

    tech_spec = input.get("tech_spec", {})
    enriched_spec = input.get("enriched_spec", {})
    spec_id = tech_spec.get("spec_id", "")
    pipeline_id = input.get("pipeline_id", "")
    org_id = input.get("org_id", "")
    model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

    set_pipeline_context(pipeline_id=pipeline_id, agent_role="pm", org_id=org_id)

    pipeline_log = log.bind(
        activity="run_task_decomposition",
        spec_id=spec_id,
        model=model,
    )
    pipeline_log.info("starting task decomposition (real agent)")
    start = time.monotonic()

    try:
        result, cost = await run_pm_agent_elastic(
            tech_spec, enriched_spec, pipeline_id=pipeline_id,
        )
        elapsed = time.monotonic() - start

        if result is not None:
            tickets = result.get("tickets", [])
            pipeline_log.info(
                "task decomposition complete",
                success=True,
                ticket_count=len(tickets),
                parallel_groups=len(result.get("execution_order", [])),
                cost_usd=round(cost, 4),
                duration_seconds=round(elapsed, 2),
            )
            await _persist_stage(
                input.get("pipeline_id", ""),
                "task_decomposition",
                result,
                cost,
                pipeline_log,
            )
            return StageResult(
                stage=PipelineStage.TASK_DECOMPOSITION,
                success=True,
                artifact=result,
                cost_usd=cost,
                duration_seconds=round(elapsed, 2),
            )

        pipeline_log.warning(
            "task decomposition failed — no valid output after retries",
            cost_usd=round(cost, 4),
            duration_seconds=round(elapsed, 2),
        )
        error = ValidationError(
            "PM agent failed to produce valid PRDBoard after retries",
            pipeline_id=pipeline_id,
            stage="task_decomposition",
            agent_role="pm",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "task decomposition errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="task_decomposition",
            agent_role="pm",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Stage 4b — Project Scaffold
# ---------------------------------------------------------------------------


@activity.defn(name="run_scaffold_project")
async def run_scaffold_project(input: dict) -> StageResult:
    """Create the base git repo and scaffold the project structure.

    Runs once after task decomposition and before the coding swarm.
    Uses ``WorktreeManager.setup_repo`` to initialise the git repo, then
    ``scaffold_project`` to generate config files, directories, and shared
    utilities from the TechSpec.

    Input keys: pipeline_id (str), tech_spec (dict), project_name (str)

    In test mode (``FORGE_TEST_MODE=1``), returns a mock result.
    """
    pipeline_id = input.get("pipeline_id", "")
    tech_spec = input.get("tech_spec", {})
    project_name = input.get("project_name", "")

    pipeline_log = log.bind(
        activity="run_scaffold_project",
        pipeline_id=pipeline_id,
        project_name=project_name,
    )
    pipeline_log.info("starting project scaffold")
    start = time.monotonic()

    # -- Test mode: return mock scaffold result ----------------------------
    if os.environ.get("FORGE_TEST_MODE") == "1":
        mock_repo_path = f"/tmp/forge/{pipeline_id}/project"
        elapsed = time.monotonic() - start
        pipeline_log.info(
            "scaffold complete (test mode)",
            repo_path=mock_repo_path,
            duration_seconds=round(elapsed, 2),
        )
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=True,
            artifact={"repo_path": mock_repo_path, "stack": "mock"},
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # -- Real mode: setup repo + scaffold ----------------------------------
    try:
        repo_path = f"/tmp/forge/{pipeline_id}/project"
        wt_dir = f"/tmp/forge/{pipeline_id}/worktrees"

        mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)
        await mgr.setup_repo(tech_spec)
        pipeline_log.info("base repo initialised", repo_path=repo_path)

        await scaffold_project(repo_path, tech_spec)
        pipeline_log.info("project scaffolded", repo_path=repo_path)

        elapsed = time.monotonic() - start
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=True,
            artifact={"repo_path": repo_path},
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "scaffold errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="task_decomposition",
            agent_role="scaffold",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Stage 4c — Validate & optimise execution order
# ---------------------------------------------------------------------------


@activity.defn(name="run_validate_execution_order")
async def run_validate_execution_order(input: dict) -> StageResult:
    """Validate the PM's execution_order and auto-fix if possible.

    Runs after task decomposition and before the coding swarm.  Catches
    file-ownership conflicts, dependency ordering mistakes, and missed
    tickets.

    If validation errors are found:
      1. Detect file ownership conflicts
      2. Suggest and apply fixes (add dependency edges, reassign ownership)
      3. Re-optimise execution order for maximum parallelism
      4. Re-validate — if still broken, return a failure for CTO escalation

    Input keys: pipeline_id (str), prd_board (dict), tech_spec (dict)
    """
    pipeline_id = input.get("pipeline_id", "")
    prd_board = input.get("prd_board", {})

    pipeline_log = log.bind(
        activity="run_validate_execution_order",
        pipeline_id=pipeline_id,
    )
    pipeline_log.info("validating execution order")
    start = time.monotonic()

    # -- Test mode -----------------------------------------------------------
    if os.environ.get("FORGE_TEST_MODE") == "1":
        elapsed = time.monotonic() - start
        pipeline_log.info("execution order validation complete (test mode)")
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=True,
            artifact={
                "prd_board": prd_board,
                "validation_errors": [],
                "optimised": False,
            },
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # -- Real mode -----------------------------------------------------------
    errors = validate_execution_order(prd_board)

    if not errors:
        # Valid — but still try to optimise parallelism
        original_groups = len(prd_board.get("execution_order", []))
        optimised = optimize_execution_order(prd_board)
        was_optimised = len(optimised) < original_groups

        if was_optimised:
            prd_board["execution_order"] = optimised
            pipeline_log.info(
                "execution order optimised (no errors)",
                original_groups=original_groups,
                optimised_groups=len(optimised),
            )

        elapsed = time.monotonic() - start
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=True,
            artifact={
                "prd_board": prd_board,
                "validation_errors": [],
                "optimised": was_optimised,
            },
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # Errors found — attempt auto-fix
    pipeline_log.warning(
        "execution order has errors, attempting auto-fix",
        error_count=len(errors),
    )

    # Detect and fix file ownership conflicts
    tickets = prd_board.get("tickets", [])
    conflicts = detect_file_ownership_conflicts(tickets)

    if conflicts:
        suggestions = suggest_file_ownership_fixes(conflicts, tickets)
        apply_ownership_fixes(prd_board, suggestions)
        pipeline_log.info(
            "applied file ownership fixes",
            fix_count=len(suggestions),
        )
    else:
        # No file conflicts — just re-optimise the ordering
        prd_board["execution_order"] = optimize_execution_order(prd_board)

    # Re-validate after fixes
    remaining_errors = validate_execution_order(prd_board)
    elapsed = time.monotonic() - start

    if remaining_errors:
        pipeline_log.error(
            "execution order still invalid after auto-fix",
            remaining_errors=remaining_errors,
        )
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=False,
            artifact={
                "prd_board": prd_board,
                "validation_errors": remaining_errors,
                "original_errors": errors,
                "optimised": True,
            },
            error=(f"Execution order invalid after auto-fix: {'; '.join(remaining_errors)}"),
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    pipeline_log.info(
        "execution order fixed and validated",
        original_errors=len(errors),
    )
    return StageResult(
        stage=PipelineStage.TASK_DECOMPOSITION,
        success=True,
        artifact={
            "prd_board": prd_board,
            "validation_errors": [],
            "original_errors": errors,
            "optimised": True,
        },
        cost_usd=0.0,
        duration_seconds=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Stage 5 — Coding
# ---------------------------------------------------------------------------


@activity.defn(name="run_coding_task")
async def run_coding_task(input: CodingTaskInput) -> CodingTaskResult:
    """Implement a single ticket in an isolated git worktree.

    Receives a CodingTaskInput dataclass directly from the workflow.

    In test mode (``FORGE_TEST_MODE=1``), returns mock data so the full
    pipeline can be exercised without git repos or LLM calls.
    """
    ticket_key = input.ticket.get("ticket_key", "unknown")
    branch_name = input.branch_name or f"forge/{ticket_key.lower()}"
    agent_id = f"coding-{ticket_key}-{input.pipeline_id[:8]}"
    pipeline_log = log.bind(
        activity="run_coding_task",
        pipeline_id=input.pipeline_id,
        ticket_key=ticket_key,
        branch=branch_name,
        agent_id=agent_id,
    )
    pipeline_log.info("starting coding task")
    start = time.monotonic()

    # Acquire a ticket lock to prevent duplicate assignment
    try:
        wm = get_working_memory()
        locked = await wm.set_ticket_lock(input.pipeline_id, ticket_key, agent_id)
        if not locked:
            pipeline_log.warning("ticket already locked by another agent")
            return CodingTaskResult(
                ticket_id=ticket_key,
                success=False,
                error=f"Ticket {ticket_key} is already locked by another agent",
                cost_usd=0.0,
            )
    except Exception as exc:
        # Best-effort: if Redis is down, proceed without locking
        pipeline_log.warning("ticket lock failed, proceeding without lock", error=str(exc))

    # Record ticket execution start in PostgreSQL
    await _persist_ticket_start(
        input.pipeline_id,
        ticket_key,
        branch_name,
        pipeline_log,
    )

    try:
        # -- Test mode: return mock data without real git / LLM -------------
        if os.environ.get("FORGE_TEST_MODE") == "1":
            files_owned = input.ticket.get("files_owned", [])
            code_artifact = {
                "ticket_key": ticket_key,
                "git_branch": branch_name,
                "files_created": list(files_owned),
                "files_modified": [],
                "test_results": {
                    "total": 2,
                    "passed": 2,
                    "failed": 0,
                    "skipped": 0,
                    "duration_seconds": 1.2,
                    "details": [
                        f"test_{ticket_key.lower().replace('-', '_')}_create — PASSED",
                        f"test_{ticket_key.lower().replace('-', '_')}_validate — PASSED",
                    ],
                },
                "lint_passed": True,
                "notes": "Mock implementation (FORGE_TEST_MODE)",
            }
            elapsed = time.monotonic() - start
            pipeline_log.info(
                "coding task complete (test mode)",
                files_created=len(files_owned),
                duration_seconds=round(elapsed, 2),
            )
            await _persist_ticket_result(
                input.pipeline_id,
                ticket_key,
                code_artifact,
                [],
                1,
                "completed",
                0.0,
                pipeline_log,
            )
            return CodingTaskResult(
                ticket_id=ticket_key,
                success=True,
                code_artifact=code_artifact,
                cost_usd=0.0,
            )

        # -- Real mode: worktree + coding agent -----------------------------
        try:
            worktree_path = input.worktree_path

            # If no worktree path was provided, create or reset one
            if not worktree_path:
                base_project = input.repo_path or os.environ.get(
                    "FORGE_PROJECT_PATH", "/tmp/forge/project"
                )
                wt_dir = os.environ.get(
                    "FORGE_WORKTREES_DIR",
                    f"/tmp/forge/{input.pipeline_id}/worktrees",
                )
                mgr = WorktreeManager(base_project, worktrees_dir=wt_dir)
                if input.reuse_worktree:
                    worktree_path = await mgr.reset_worktree(ticket_key, branch_name)
                    pipeline_log.info("worktree reset for reuse", worktree_path=worktree_path)
                else:
                    worktree_path = await mgr.create_worktree(ticket_key, branch_name)
                    pipeline_log.info("worktree created", worktree_path=worktree_path)

            result, cost = await run_coding_agent_task(
                ticket=input.ticket,
                tech_spec_context=input.tech_spec_context,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
            elapsed = time.monotonic() - start

            if result is not None:
                pipeline_log.info(
                    "coding task complete",
                    files_created=len(result.get("files_created", [])),
                    files_modified=len(result.get("files_modified", [])),
                    cost_usd=round(cost, 4),
                    duration_seconds=round(elapsed, 2),
                )
                await _persist_ticket_result(
                    input.pipeline_id,
                    ticket_key,
                    result,
                    [],
                    1,
                    "completed",
                    cost,
                    pipeline_log,
                )
                return CodingTaskResult(
                    ticket_id=ticket_key,
                    success=True,
                    code_artifact=result,
                    cost_usd=cost,
                )

            pipeline_log.warning(
                "coding agent returned no result",
                duration_seconds=round(elapsed, 2),
            )
            error = ValidationError(
                "Coding agent failed to produce output",
                pipeline_id=input.pipeline_id,
                stage="coding",
                agent_role="engineer",
            )
            await _get_error_reporter().report(error)
            _raise_as_temporal(error)

        except ForgeError:
            raise
        except Exception as exc:
            elapsed = time.monotonic() - start
            pipeline_log.error(
                "coding task errored",
                error=str(exc),
                traceback=traceback.format_exc(),
                duration_seconds=round(elapsed, 2),
            )
            error = _classify_and_wrap(
                exc,
                pipeline_id=input.pipeline_id,
                stage="coding",
                agent_role="engineer",
            )
            await _get_error_reporter().report(error)
            _raise_as_temporal(error)
    finally:
        # Always release the ticket lock when done
        await _release_ticket_lock(input.pipeline_id, ticket_key, pipeline_log)


# ---------------------------------------------------------------------------
# Stage 6 — QA Review
# ---------------------------------------------------------------------------


@activity.defn(name="run_qa_review")
async def run_qa_review(input: QATaskInput) -> QATaskResult:
    """Review a code artifact against its ticket's acceptance criteria.

    Calls the real LangGraph-based QA agent to produce a validated
    QAReview.  Falls back to a failed QATaskResult on any error.

    Receives a QATaskInput dataclass directly from the workflow.
    """

    ticket_key = input.ticket.get("ticket_key", "unknown")
    model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

    set_pipeline_context(
        pipeline_id=input.pipeline_id,
        agent_role="qa",
        ticket_id=ticket_key,
    )

    pipeline_log = log.bind(
        activity="run_qa_review",
        pipeline_id=input.pipeline_id,
        ticket_key=ticket_key,
        model=model,
    )
    pipeline_log.info("starting QA review (real agent)")
    start = time.monotonic()

    try:
        result, cost = await run_qa_agent(
            ticket=input.ticket,
            code_artifact=input.code_artifact,
            coding_standards=input.coding_standards,
        )
        elapsed = time.monotonic() - start

        if result is not None:
            verdict = result.get("verdict", "unknown")
            score = result.get("code_quality_score", 0)
            pipeline_log.info(
                "QA review complete",
                success=True,
                verdict=verdict,
                score=score,
                cost_usd=round(cost, 4),
                duration_seconds=round(elapsed, 2),
            )
            return QATaskResult(
                ticket_id=ticket_key,
                verdict=verdict,
                review=result,
                cost_usd=cost,
            )

        pipeline_log.warning(
            "QA review failed — no valid output after retries",
            cost_usd=round(cost, 4),
            duration_seconds=round(elapsed, 2),
        )
        error = LLMError(
            "QA agent failed to produce valid QAReview after retries",
            pipeline_id=input.pipeline_id,
            stage="qa_review",
            agent_role="qa",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "QA review errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=input.pipeline_id,
            stage="qa_review",
            agent_role="qa",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Stage 7 — Merge
# ---------------------------------------------------------------------------


@activity.defn(name="run_merge")
async def run_merge(input: dict) -> StageResult:
    """Merge all approved code artifact branches into the main branch.

    Input keys: pipeline_id (str), code_artifacts (list[dict]),
                qa_reviews (list[dict])

    In test mode (``FORGE_TEST_MODE=1``), returns mock merge data.
    """
    pipeline_id = input.get("pipeline_id", "")
    artifacts = input.get("code_artifacts", [])

    pipeline_log = log.bind(
        activity="run_merge",
        pipeline_id=pipeline_id,
        artifact_count=len(artifacts),
    )
    pipeline_log.info("starting merge")
    start = time.monotonic()

    # -- Test mode: return mock merge result --------------------------------
    if os.environ.get("FORGE_TEST_MODE") == "1":
        merged_branches = [a.get("git_branch", "unknown") for a in artifacts]
        merge_result = {
            "merged_branches": merged_branches,
            "merge_commit": "mock-merge-sha",
            "conflicts": [],
            "pipeline_id": pipeline_id,
        }
        elapsed = time.monotonic() - start
        pipeline_log.info(
            "merge complete (test mode)",
            branches_merged=len(merged_branches),
            duration_seconds=round(elapsed, 2),
        )
        return StageResult(
            stage=PipelineStage.MERGE,
            success=True,
            artifact=merge_result,
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # -- Real mode: merge each branch via WorktreeManager -------------------
    base_project = os.environ.get("FORGE_PROJECT_PATH", "/tmp/forge/project")
    wt_dir = os.environ.get(
        "FORGE_WORKTREES_DIR",
        f"/tmp/forge/{pipeline_id}/worktrees",
    )
    mgr = WorktreeManager(base_project, worktrees_dir=wt_dir)

    merged_branches: list[str] = []
    all_conflicts: list[str] = []
    last_merge_commit: str | None = None

    for artifact in artifacts:
        branch = artifact.get("git_branch", "")
        ticket_key = artifact.get("ticket_key", "unknown")
        if not branch:
            pipeline_log.warning("artifact has no git_branch, skipping", ticket_key=ticket_key)
            continue

        pipeline_log.info("merging branch", branch=branch, ticket_key=ticket_key)

        try:
            merge_info = await mgr.merge_worktree(ticket_key, branch)
        except Exception as exc:
            pipeline_log.error(
                "merge errored",
                branch=branch,
                ticket_key=ticket_key,
                error=str(exc),
            )
            all_conflicts.append(f"{branch}: {exc}")
            continue

        if merge_info["success"]:
            merged_branches.append(branch)
            last_merge_commit = merge_info["merge_commit"]
            pipeline_log.info(
                "branch merged",
                branch=branch,
                commit=merge_info["merge_commit"],
            )
        else:
            all_conflicts.extend(f"{branch}: {c}" for c in merge_info.get("conflicts", [branch]))
            pipeline_log.warning(
                "merge conflict",
                branch=branch,
                conflicts=merge_info.get("conflicts", []),
            )

    elapsed = time.monotonic() - start
    success = len(all_conflicts) == 0

    merge_result = {
        "merged_branches": merged_branches,
        "merge_commit": last_merge_commit,
        "conflicts": all_conflicts,
        "pipeline_id": pipeline_id,
    }

    if success:
        pipeline_log.info(
            "merge complete",
            branches_merged=len(merged_branches),
            duration_seconds=round(elapsed, 2),
        )
        return StageResult(
            stage=PipelineStage.MERGE,
            success=True,
            artifact=merge_result,
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    pipeline_log.warning(
        "merge completed with conflicts",
        branches_merged=len(merged_branches),
        conflict_count=len(all_conflicts),
        duration_seconds=round(elapsed, 2),
    )
    error = MergeConflictError(
        f"Merge conflicts: {'; '.join(all_conflicts[:5])}",
        pipeline_id=pipeline_id,
        stage="merge",
        agent_role="merge",
        conflicting_files=all_conflicts,
    )
    await _get_error_reporter().report(error)
    _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# CTO Intervention
# ---------------------------------------------------------------------------


@activity.defn(name="run_cto_intervention")
async def run_cto_intervention(input: dict) -> StageResult:
    """Invoke the CTO agent to resolve a pipeline issue.

    Input keys: trigger_type (str), trigger_description (str),
                pipeline_state (dict), context (dict)

    In test mode (``FORGE_TEST_MODE=1``), returns a mock "continue" decision.
    """
    trigger_type = input.get("trigger_type", "unknown")
    trigger_desc = input.get("trigger_description", "")
    pipeline_state = input.get("pipeline_state", {})
    context = input.get("context", {})

    set_pipeline_context(
        pipeline_id=pipeline_state.get("pipeline_id", ""),
        agent_role="cto",
        org_id=input.get("org_id", ""),
    )

    pipeline_log = log.bind(
        activity="run_cto_intervention",
        trigger_type=trigger_type,
    )
    pipeline_log.info("starting CTO intervention")
    start = time.monotonic()

    # -- Test mode: return a mock "continue" decision -----------------------
    if os.environ.get("FORGE_TEST_MODE") == "1":
        mock_decision = {
            "intervention_type": trigger_type,
            "decision": "Continue with current approach (test mode)",
            "rationale": "Mock CTO decision for testing",
            "pipeline_action": "continue",
            "ticket_updates": [],
            "instructions_to_engineer": "",
            "instructions_to_qa": "",
        }
        elapsed = time.monotonic() - start
        pipeline_log.info(
            "CTO intervention complete (test mode)",
            pipeline_action="continue",
            duration_seconds=round(elapsed, 2),
        )
        await _persist_cto_intervention(
            pipeline_state.get("pipeline_id", ""),
            trigger_type,
            trigger_desc,
            mock_decision,
            pipeline_log,
        )
        return StageResult(
            stage=PipelineStage.QA_REVIEW,
            success=True,
            artifact=mock_decision,
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # -- Real mode: call CTO agent ------------------------------------------
    try:
        result, cost = await run_cto_agent(
            trigger_type=trigger_type,
            trigger_description=trigger_desc,
            pipeline_state=pipeline_state,
            context=context,
        )
        elapsed = time.monotonic() - start

        if result is not None:
            pipeline_action = result.get("pipeline_action", "continue")
            pipeline_log.info(
                "CTO intervention complete",
                pipeline_action=pipeline_action,
                intervention_type=result.get("intervention_type"),
                cost_usd=round(cost, 4),
                duration_seconds=round(elapsed, 2),
            )
            await _persist_cto_intervention(
                pipeline_state.get("pipeline_id", ""),
                trigger_type,
                trigger_desc,
                result,
                pipeline_log,
            )
            return StageResult(
                stage=PipelineStage.QA_REVIEW,
                success=True,
                artifact=result,
                cost_usd=cost,
                duration_seconds=round(elapsed, 2),
            )

        pipeline_log.warning(
            "CTO agent returned no result",
            cost_usd=round(cost, 4),
            duration_seconds=round(elapsed, 2),
        )
        error = LLMError(
            "CTO agent failed to produce a valid decision",
            pipeline_id=pipeline_state.get("pipeline_id", ""),
            stage="cto",
            agent_role="cto",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "CTO intervention errored",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_state.get("pipeline_id", ""),
            stage="cto",
            agent_role="cto",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------

# Module-level BatchEventEmitter singleton (lazily initialised)
_batch_emitter: BatchEventEmitter | None = None


def _get_batch_emitter() -> BatchEventEmitter:
    """Return (and start) the module-level BatchEventEmitter."""
    global _batch_emitter
    if _batch_emitter is None:
        wm = get_working_memory()
        _batch_emitter = BatchEventEmitter(wm)
        _batch_emitter.start()
    return _batch_emitter


@activity.defn(name="emit_pipeline_event")
async def emit_pipeline_event(event: PipelineEvent) -> None:
    """Broadcast a pipeline event via structured logging, Redis pub/sub,
    and PostgreSQL persistence.

    Publishes to Redis channel ``forge:events:{pipeline_id}`` so the
    WebSocket endpoint can stream events to the dashboard in real time.
    Also inserts a row into the ``agent_events`` table for persistence.

    Both Redis and PostgreSQL operations are best-effort — failures are
    logged but never block the pipeline.
    """
    pipeline_log = log.bind(
        activity="emit_pipeline_event",
        pipeline_id=event.pipeline_id,
        event_type=event.event_type,
        stage=event.stage,
    )
    pipeline_log.info(
        "pipeline event",
        payload=event.payload,
        agent_role=event.agent_role,
        agent_id=event.agent_id,
        timestamp=event.timestamp,
    )

    # Build event dict for pub/sub and PG.
    # Include ``id`` and ``created_at`` so WebSocket events match the
    # AgentEvent TypeScript interface expected by the React dashboard.
    event_dict = {
        "id": uuid.uuid4().hex,
        "pipeline_id": event.pipeline_id,
        "event_type": event.event_type,
        "stage": str(event.stage) if event.stage else None,
        "agent_role": event.agent_role,
        "agent_id": event.agent_id,
        "payload": event.payload,
        "timestamp": event.timestamp,
        "created_at": event.timestamp,
    }

    # -- Publish to Redis pub/sub via batched emitter -----------------------
    try:
        emitter = _get_batch_emitter()
        await emitter.emit(event.pipeline_id, event_dict)
    except Exception as exc:
        pipeline_log.warning("redis publish failed", error=str(exc))

    # -- Persist to PostgreSQL via StateStore --------------------------------
    try:
        store = get_state_store()
        payload = dict(event.payload)
        if event.stage:
            payload["stage"] = str(event.stage)
        await store.record_event(
            pipeline_id=event.pipeline_id,
            agent_role=event.agent_role or "",
            event_type=event.event_type,
            payload=payload,
            agent_id=event.agent_id,
        )
    except Exception as exc:
        pipeline_log.warning("pg insert failed", error=str(exc))


# ---------------------------------------------------------------------------
# State persistence helpers (best-effort — never block the pipeline)
# ---------------------------------------------------------------------------


async def _persist_stage(
    pipeline_id: str,
    stage: str,
    artifact: dict,
    cost: float,
    pipeline_log: structlog.BoundLogger,
) -> None:
    """Persist a stage artifact and cost delta to PostgreSQL."""
    if not pipeline_id:
        return
    try:
        store = get_state_store()
        await store.update_stage(pipeline_id, stage, artifact)
        if cost > 0:
            await store.update_cost(pipeline_id, cost)
    except Exception as exc:
        pipeline_log.warning("state persistence failed", error=str(exc))


async def _persist_ticket_start(
    pipeline_id: str,
    ticket_key: str,
    branch_name: str,
    pipeline_log: structlog.BoundLogger,
) -> None:
    """Record a ticket execution start in PostgreSQL."""
    if not pipeline_id:
        return
    try:
        store = get_state_store()
        await store.record_ticket_execution(
            pipeline_id,
            ticket_key,
            "in_progress",
            branch_name=branch_name,
        )
    except Exception as exc:
        pipeline_log.warning("ticket start persistence failed", error=str(exc))


async def _persist_ticket_result(
    pipeline_id: str,
    ticket_key: str,
    code_artifact: dict | None,
    qa_reviews: list[dict],
    revision_count: int,
    status: str,
    cost_usd: float,
    pipeline_log: structlog.BoundLogger,
    verdict: str | None = None,
) -> None:
    """Record ticket coding/QA results in PostgreSQL."""
    if not pipeline_id:
        return
    try:
        store = get_state_store()
        await store.update_ticket_result(
            pipeline_id,
            ticket_key,
            code_artifact,
            qa_reviews,
            revision_count,
            status,
            cost_usd,
            verdict=verdict,
        )
    except Exception as exc:
        pipeline_log.warning("ticket result persistence failed", error=str(exc))


async def _release_ticket_lock(
    pipeline_id: str,
    ticket_key: str,
    pipeline_log: structlog.BoundLogger,
) -> None:
    """Release a ticket lock in Redis (best-effort)."""
    try:
        wm = get_working_memory()
        await wm.release_ticket_lock(pipeline_id, ticket_key)
    except Exception as exc:
        pipeline_log.warning("ticket lock release failed", error=str(exc))


async def _persist_cto_intervention(
    pipeline_id: str,
    trigger_type: str,
    trigger_description: str,
    decision: dict,
    pipeline_log: structlog.BoundLogger,
) -> None:
    """Record a CTO intervention in PostgreSQL."""
    if not pipeline_id:
        return
    try:
        store = get_state_store()
        await store.record_cto_intervention(
            pipeline_id,
            trigger_type,
            trigger_description,
            decision,
        )
    except Exception as exc:
        pipeline_log.warning("cto intervention persistence failed", error=str(exc))


# ---------------------------------------------------------------------------
# Pipeline lifecycle activities
# ---------------------------------------------------------------------------


@activity.defn(name="initialize_pipeline_state")
async def initialize_pipeline_state(input: dict) -> None:
    """Create the pipeline_runs row in PostgreSQL at pipeline start."""
    pipeline_id = input.get("pipeline_id", "")
    business_spec = input.get("business_spec", "")
    project_name = input.get("project_name", "")

    init_log = log.bind(activity="initialize_pipeline_state", pipeline_id=pipeline_id)
    init_log.info("initialising pipeline state in PostgreSQL")

    try:
        store = get_state_store()
        await store.create_pipeline_run(pipeline_id, business_spec, project_name)
        init_log.info("pipeline state initialised")
    except Exception as exc:
        # Best-effort: log but don't fail the pipeline
        init_log.warning("failed to initialise pipeline state", error=str(exc))


@activity.defn(name="finalize_pipeline_state")
async def finalize_pipeline_state(input: dict) -> None:
    """Update the pipeline status to its terminal state in PostgreSQL."""
    pipeline_id = input.get("pipeline_id", "")
    status = input.get("status", "completed")

    final_log = log.bind(activity="finalize_pipeline_state", pipeline_id=pipeline_id)
    final_log.info("finalising pipeline state", status=status)

    try:
        store = get_state_store()
        await store.update_status(pipeline_id, status)
        final_log.info("pipeline state finalised", status=status)
    except Exception as exc:
        final_log.warning("failed to finalise pipeline state", error=str(exc))


# ---------------------------------------------------------------------------
# Memory extraction & storage activities
# ---------------------------------------------------------------------------


@activity.defn(name="extract_pipeline_lessons")
async def extract_pipeline_lessons(input: dict) -> list[str]:
    """Analyse a completed pipeline and extract reusable lessons.

    Calls SemanticMemory.extract_lessons_from_pipeline to generate 3-5
    lessons, then stores key decisions (tech stack, architecture pattern)
    as separate decision memories.

    Input keys: pipeline_id (str), pipeline_result (dict),
                org_id (str, optional), user_id (str, optional)

    Returns the list of extracted lesson strings (empty on failure).
    """
    pipeline_id = input.get("pipeline_id", "")
    pipeline_result = input.get("pipeline_result", {})
    org_id = input.get("org_id", "") or ""
    user_id = input.get("user_id", "") or ""

    lesson_log = log.bind(activity="extract_pipeline_lessons", pipeline_id=pipeline_id)
    lesson_log.info("starting post-pipeline lesson extraction")

    # In test mode, return mock lessons without touching the DB
    if os.environ.get("FORGE_TEST_MODE") == "1":
        mock_lessons = [
            "Always validate input parameters at API boundaries.",
            "Use structured logging from the start to simplify debugging.",
        ]
        lesson_log.info("lesson extraction complete (test mode)", count=len(mock_lessons))
        return mock_lessons

    try:
        from memory.semantic_memory import SemanticMemory

        mem = SemanticMemory()

        # Extract and store lessons (extract_lessons_from_pipeline stores them internally)
        lessons = await mem.extract_lessons_from_pipeline(
            pipeline_id, pipeline_result,
            org_id=org_id or None, user_id=user_id or None,
        )

        # Store key architectural decisions as separate decision memories
        tech_spec = pipeline_result.get("tech_spec")
        if isinstance(tech_spec, dict):
            tech_stack = tech_spec.get("tech_stack", {})
            if tech_stack:
                stack_summary = ", ".join(f"{k}: {v}" for k, v in tech_stack.items())
                await mem.store_decision(
                    pipeline_id=pipeline_id,
                    decision_type="tech_stack",
                    decision=f"Selected tech stack: {stack_summary}",
                    rationale="Chosen by architect agent based on enriched spec analysis",
                    context={"tech_stack": tech_stack},
                    org_id=org_id or None, user_id=user_id or None,
                )

            # Store architecture pattern if services are defined
            services = tech_spec.get("services", [])
            if services:
                svc_names = [s.get("name", "?") for s in services]
                await mem.store_decision(
                    pipeline_id=pipeline_id,
                    decision_type="architecture_pattern",
                    decision=f"Architecture with services: {', '.join(svc_names)}",
                    rationale="Service decomposition from architect agent",
                    context={"service_count": len(services)},
                    org_id=org_id or None, user_id=user_id or None,
                )

        lesson_log.info("lesson extraction complete", count=len(lessons))
        return lessons

    except Exception as exc:
        lesson_log.warning("lesson extraction failed", error=str(exc))
        return []


@activity.defn(name="store_agent_memory")
async def store_agent_memory(input: dict) -> bool:
    """Store a single lesson or decision in semantic memory.

    Used by the workflow to record QA revision lessons and CTO decisions
    as they happen, so agents learn incrementally — not just at the end.

    Input keys:
        pipeline_id (str), agent_role (str), content (str),
        memory_type (str: "lesson" | "decision"),
        metadata (dict, optional),
        decision_type (str, optional — for decisions),
        rationale (str, optional — for decisions),
        org_id (str, optional), user_id (str, optional)

    Returns True on success, False on failure.
    """
    pipeline_id = input.get("pipeline_id", "")
    agent_role = input.get("agent_role", "system")
    content = input.get("content", "")
    memory_type = input.get("memory_type", "lesson")
    org_id = input.get("org_id", "") or ""
    user_id = input.get("user_id", "") or ""

    mem_log = log.bind(
        activity="store_agent_memory",
        pipeline_id=pipeline_id,
        agent_role=agent_role,
        memory_type=memory_type,
    )

    if not content:
        mem_log.debug("empty content, skipping memory storage")
        return False

    # In test mode, just log and return
    if os.environ.get("FORGE_TEST_MODE") == "1":
        mem_log.info("memory stored (test mode)", preview=content[:80])
        return True

    try:
        from memory.semantic_memory import SemanticMemory

        mem = SemanticMemory()
        metadata = input.get("metadata") or {}

        if memory_type == "decision":
            await mem.store_decision(
                pipeline_id=pipeline_id,
                decision_type=input.get("decision_type", "general"),
                decision=content,
                rationale=input.get("rationale", ""),
                context=metadata,
                org_id=org_id or None, user_id=user_id or None,
            )
        else:
            await mem.store_lesson(
                agent_role=agent_role,
                pipeline_id=pipeline_id,
                lesson=content,
                metadata=metadata,
                org_id=org_id or None, user_id=user_id or None,
            )

        mem_log.info("memory stored", preview=content[:80])
        return True

    except Exception as exc:
        mem_log.warning("memory storage failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Group coding activity (coding + QA + merge in a single activity)
# ---------------------------------------------------------------------------


@activity.defn(name="run_coding_group")
async def run_coding_group(input: GroupTaskInput) -> GroupTaskResult:
    """Execute a full ticket group: parallel coding → parallel QA → merge.

    Uses :class:`SwarmCoordinator` internally for asyncio-based parallelism
    within a single Temporal activity.  This avoids per-ticket activity
    overhead for small groups (2-4 tickets).

    Stages:
      1. Parallel coding via ``SwarmCoordinator.execute_group``
      2. Parallel QA review for each completed ticket
      3. Merge approved tickets with conflict resolution
    """
    pipeline_log = log.bind(
        activity="run_coding_group",
        pipeline_id=input.pipeline_id,
        group_index=input.group_index,
        ticket_count=len(input.tickets),
    )
    pipeline_log.info("starting coding group")
    start = time.monotonic()
    total_cost = 0.0
    failed_tickets: list[str] = []

    set_pipeline_context(pipeline_id=input.pipeline_id, agent_role="swarm", org_id=input.org_id)

    # -- Test mode: return mock group result --------------------------------
    if os.environ.get("FORGE_TEST_MODE") == "1":
        mock_ticket_results = []
        for ticket in input.tickets:
            tk = ticket.get("ticket_key", "unknown")
            mock_ticket_results.append(
                {
                    "ticket_id": tk,
                    "success": True,
                    "code_artifact": {
                        "ticket_key": tk,
                        "git_branch": f"forge/{tk.lower()}",
                        "files_created": ticket.get("files_owned", []),
                        "files_modified": [],
                    },
                    "cost_usd": 0.0,
                }
            )
        elapsed = time.monotonic() - start
        pipeline_log.info(
            "coding group complete (test mode)",
            duration_seconds=round(elapsed, 2),
        )
        return GroupTaskResult(
            group_index=input.group_index,
            ticket_results=mock_ticket_results,
            qa_results=[
                {
                    "ticket_id": r["ticket_id"],
                    "verdict": "approved",
                    "review": {"verdict": "approved", "code_quality_score": 9},
                    "cost_usd": 0.0,
                }
                for r in mock_ticket_results
            ],
            merge_result={
                "merged": [r["ticket_id"] for r in mock_ticket_results],
                "conflicted": [],
            },
            total_cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # -- Real mode ----------------------------------------------------------
    repo_path = input.repo_path or os.environ.get(
        "FORGE_PROJECT_PATH",
        f"/tmp/forge/{input.pipeline_id}/project",
    )
    wt_dir = os.environ.get(
        "FORGE_WORKTREES_DIR",
        f"/tmp/forge/{input.pipeline_id}/worktrees",
    )

    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)
    wm = get_working_memory()
    coordinator = SwarmCoordinator(
        pipeline_id=input.pipeline_id,
        worktree_manager=mgr,
        working_memory=wm,
    )

    # 1. Parallel coding
    pipeline_log.info("phase 1: parallel coding")
    coding_results = await coordinator.execute_group(
        tickets=input.tickets,
        tech_spec_context=input.tech_spec_context,
    )

    ticket_result_dicts: list[dict] = []
    completed_results = []
    for r in coding_results:
        total_cost += r.cost_usd
        ticket_result_dicts.append(
            {
                "ticket_id": r.ticket_id,
                "success": r.success,
                "code_artifact": r.code_artifact,
                "error": r.error,
                "cost_usd": r.cost_usd,
            }
        )
        if r.success:
            completed_results.append(r)
        else:
            failed_tickets.append(r.ticket_id)

    # Persist each ticket result (best-effort)
    for r in coding_results:
        await _persist_ticket_result(
            input.pipeline_id,
            r.ticket_id,
            r.code_artifact,
            [],
            1,
            "completed" if r.success else "failed",
            r.cost_usd,
            pipeline_log,
        )

    if not completed_results:
        elapsed = time.monotonic() - start
        pipeline_log.warning("all tickets in group failed coding")
        return GroupTaskResult(
            group_index=input.group_index,
            ticket_results=ticket_result_dicts,
            failed_tickets=failed_tickets,
            total_cost_usd=total_cost,
            duration_seconds=round(elapsed, 2),
        )

    # 2. Parallel QA
    pipeline_log.info(
        "phase 2: parallel QA",
        tickets_to_review=len(completed_results),
    )
    qa_result_dicts = await _parallel_qa_reviews(
        pipeline_id=input.pipeline_id,
        completed_results=completed_results,
        tickets=input.tickets,
        coding_standards=input.coding_standards,
        pipeline_log=pipeline_log,
    )
    for qr in qa_result_dicts:
        total_cost += qr.get("cost_usd", 0.0)

    # Filter to approved tickets for merge
    approved_ids = {qr["ticket_id"] for qr in qa_result_dicts if qr.get("verdict") == "approved"}
    approved_results = [r for r in completed_results if r.ticket_id in approved_ids]

    # Tickets that failed QA are not fatal — just reported
    for qr in qa_result_dicts:
        if qr.get("verdict") != "approved" and qr["ticket_id"] not in failed_tickets:
            failed_tickets.append(qr["ticket_id"])

    # Persist QA verdicts back to ticket_executions (best-effort).
    # Pass cost_usd=0 so we don't overwrite the coding cost already stored.
    for qr in qa_result_dicts:
        await _persist_ticket_result(
            input.pipeline_id,
            qr["ticket_id"],
            None,
            [qr.get("review", {})],
            1,
            qr.get("verdict", "needs_revision"),
            0.0,
            pipeline_log,
            verdict=qr.get("verdict"),
        )

    # 3. Merge approved tickets with conflict resolution
    pipeline_log.info(
        "phase 3: merge with conflict resolution",
        approved_count=len(approved_results),
    )
    merge_result: dict = {}
    if approved_results:
        merge_result = await coordinator.merge_group(
            completed_tickets=approved_results,
            tech_spec=input.tech_spec,
            tech_spec_context=input.tech_spec_context,
            tickets=input.tickets,
        )
        total_cost += merge_result.get("resolution_cost_usd", 0.0)
    else:
        merge_result = {"merged": [], "conflicted": [], "conflict_details": []}
        pipeline_log.warning("no approved tickets to merge")

    elapsed = time.monotonic() - start
    pipeline_log.info(
        "coding group complete",
        merged=len(merge_result.get("merged", [])),
        failed=len(failed_tickets),
        total_cost=round(total_cost, 4),
        duration_seconds=round(elapsed, 2),
    )

    return GroupTaskResult(
        group_index=input.group_index,
        ticket_results=ticket_result_dicts,
        qa_results=qa_result_dicts,
        merge_result=merge_result,
        total_cost_usd=total_cost,
        failed_tickets=failed_tickets,
        duration_seconds=round(elapsed, 2),
    )


async def _parallel_qa_reviews(
    *,
    pipeline_id: str,
    completed_results: list,
    tickets: list[dict],
    coding_standards: list[str],
    pipeline_log: structlog.BoundLogger,
) -> list[dict]:
    """Run QA reviews for all completed tickets in parallel.

    Calls ``run_qa_agent`` directly (not via Temporal activity) to keep
    everything within a single activity's asyncio event loop.
    """
    from agents.qa_agent import run_qa_agent

    tickets_by_key = {t.get("ticket_key", ""): t for t in tickets}

    async def _review_one(result) -> dict:
        ticket_id = result.ticket_id
        ticket = tickets_by_key.get(ticket_id, {"ticket_key": ticket_id})
        code_artifact = result.code_artifact or {}

        try:
            review, cost = await run_qa_agent(
                ticket=ticket,
                code_artifact=code_artifact,
                coding_standards=coding_standards,
            )
            if review is not None:
                verdict = review.get("verdict", "needs_revision")
                pipeline_log.info(
                    "QA review complete",
                    ticket_id=ticket_id,
                    verdict=verdict,
                    cost_usd=round(cost, 4),
                )
                return {
                    "ticket_id": ticket_id,
                    "verdict": verdict,
                    "review": review,
                    "cost_usd": cost,
                }

            pipeline_log.warning("QA agent returned no result", ticket_id=ticket_id)
            return {
                "ticket_id": ticket_id,
                "verdict": "needs_revision",
                "review": {"error": "QA agent produced no output"},
                "cost_usd": cost,
            }

        except Exception as exc:
            pipeline_log.error(
                "QA review failed",
                ticket_id=ticket_id,
                error=str(exc),
            )
            return {
                "ticket_id": ticket_id,
                "verdict": "needs_revision",
                "review": {"error": f"QA error: {exc}"},
                "cost_usd": 0.0,
            }

    tasks = [_review_one(r) for r in completed_results]
    return list(await asyncio.gather(*tasks))


# ---------------------------------------------------------------------------
# Integration check (post-merge test suite on main)
# ---------------------------------------------------------------------------


@activity.defn(name="run_integration_check")
async def run_integration_check(input: dict) -> StageResult:
    """Run the full test suite on the merged main branch.

    Executes after all execution-order groups have been coded, reviewed,
    and merged.  Validates that the combined codebase works as a whole.

    Input keys: pipeline_id (str), repo_path (str)
    """
    pipeline_id = input.get("pipeline_id", "")
    repo_path = input.get("repo_path", "")

    pipeline_log = log.bind(
        activity="run_integration_check",
        pipeline_id=pipeline_id,
        repo_path=repo_path,
    )
    pipeline_log.info("starting integration check")
    start = time.monotonic()

    # -- Test mode ----------------------------------------------------------
    if os.environ.get("FORGE_TEST_MODE") == "1":
        elapsed = time.monotonic() - start
        pipeline_log.info("integration check complete (test mode)")
        return StageResult(
            stage=PipelineStage.MERGE,
            success=True,
            artifact={
                "test_passed": True,
                "test_summary": "All tests passed (test mode)",
                "pipeline_id": pipeline_id,
            },
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    # -- Real mode: run tests on main branch --------------------------------
    import asyncio as _asyncio

    if not repo_path:
        repo_path = os.environ.get(
            "FORGE_PROJECT_PATH",
            f"/tmp/forge/{pipeline_id}/project",
        )

    try:
        # Look for a test runner script or use pytest as default
        test_cmd = ["python", "-m", "pytest", "--tb=short", "-q"]

        proc = await _asyncio.create_subprocess_exec(
            *test_cmd,
            cwd=repo_path,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await _asyncio.wait_for(
            proc.communicate(),
            timeout=300,
        )
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        passed = proc.returncode == 0

        elapsed = time.monotonic() - start
        pipeline_log.info(
            "integration check complete",
            passed=passed,
            returncode=proc.returncode,
            duration_seconds=round(elapsed, 2),
        )

        return StageResult(
            stage=PipelineStage.MERGE,
            success=passed,
            artifact={
                "test_passed": passed,
                "test_summary": stdout[-2000:] if stdout else stderr[-2000:],
                "returncode": proc.returncode,
                "pipeline_id": pipeline_id,
            },
            error=stderr[-500:] if not passed and stderr else None,
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "integration check errored",
            error=str(exc),
            duration_seconds=round(elapsed, 2),
        )
        return StageResult(
            stage=PipelineStage.MERGE,
            success=False,
            error=f"Integration check error: {exc}",
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )


# ---------------------------------------------------------------------------
# Clone remote repo (GitHub integration)
# ---------------------------------------------------------------------------


@activity.defn(name="clone_remote_repo")
async def clone_remote_repo(input: dict) -> StageResult:
    """Clone a GitHub repo and configure git identity for the pipeline.

    Input keys:
        pipeline_id (str), repo_url (str), repo_owner (str),
        repo_name (str), git_identity_name (str | None),
        tech_spec (dict)
    """
    pipeline_id = input.get("pipeline_id", "")
    repo_url = input.get("repo_url", "")
    repo_owner = input.get("repo_owner", "")
    repo_name = input.get("repo_name", "")
    identity_name = input.get("git_identity_name")
    tech_spec = input.get("tech_spec", {})
    target_branch = input.get("target_branch")

    pipeline_log = log.bind(
        activity="clone_remote_repo",
        pipeline_id=pipeline_id,
        repo=f"{repo_owner}/{repo_name}",
    )
    pipeline_log.info("cloning remote repository")
    start = time.monotonic()

    if os.environ.get("FORGE_TEST_MODE") == "1":
        mock_path = f"/tmp/forge/{pipeline_id}/project"
        elapsed = time.monotonic() - start
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=True,
            artifact={"repo_path": mock_path, "cloned": True},
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    try:
        from integrations.git_identity import GitIdentityManager
        from integrations.github_client import GitHubClient
        from integrations.repo_connector import RepoConnector

        # Resolve identity
        mgr = GitIdentityManager()
        if identity_name:
            identity = mgr.get_identity(identity_name)
            if identity is None:
                identity = mgr.resolve_identity(repo_url)
        else:
            identity = mgr.resolve_identity(repo_url)

        repo_path = f"/tmp/forge/{pipeline_id}/project"
        wt_dir = f"/tmp/forge/{pipeline_id}/worktrees"
        os.makedirs(wt_dir, exist_ok=True)

        async with GitHubClient(identity) as gh:
            connector = RepoConnector(
                gh, identity, repo_owner, repo_name,
                target_branch=target_branch,
            )
            repo_path = await connector.initialize(repo_path)
            await connector.sync_from_remote(repo_path)

        elapsed = time.monotonic() - start
        pipeline_log.info(
            "repo cloned",
            repo_path=repo_path,
            duration_seconds=round(elapsed, 2),
        )
        return StageResult(
            stage=PipelineStage.TASK_DECOMPOSITION,
            success=True,
            artifact={"repo_path": repo_path, "cloned": True},
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "clone_remote_repo failed",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="task_decomposition",
            agent_role="clone",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Push pipeline results to GitHub
# ---------------------------------------------------------------------------


@activity.defn(name="push_pipeline_results")
async def push_pipeline_results(input: dict) -> StageResult:
    """Push pipeline code to GitHub and create PRs.

    Input keys:
        pipeline_id (str), repo_path (str), repo_owner (str),
        repo_name (str), git_identity_name (str | None),
        repo_url (str), pr_strategy (str), code_artifacts (list),
        issue_number (int | None), project_name (str)
    """
    pipeline_id = input.get("pipeline_id", "")
    repo_path = input.get("repo_path", "")
    repo_owner = input.get("repo_owner", "")
    repo_name = input.get("repo_name", "")
    identity_name = input.get("git_identity_name")
    repo_url = input.get("repo_url", "")
    pr_strategy = input.get("pr_strategy", "single_pr")
    code_artifacts = input.get("code_artifacts", [])
    issue_number = input.get("issue_number")
    target_branch = input.get("target_branch")

    pipeline_log = log.bind(
        activity="push_pipeline_results",
        pipeline_id=pipeline_id,
        repo=f"{repo_owner}/{repo_name}",
        strategy=pr_strategy,
    )
    pipeline_log.info("pushing pipeline results to GitHub")
    start = time.monotonic()

    if os.environ.get("FORGE_TEST_MODE") == "1":
        elapsed = time.monotonic() - start
        return StageResult(
            stage=PipelineStage.MERGE,
            success=True,
            artifact={"prs": [], "branches": [], "pushed": True},
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    try:
        from integrations.git_identity import GitIdentityManager
        from integrations.github_client import GitHubClient
        from integrations.issue_tracker import IssueTracker
        from integrations.repo_connector import RepoConnector

        mgr = GitIdentityManager()
        if identity_name:
            identity = mgr.get_identity(identity_name)
            if identity is None:
                identity = mgr.resolve_identity(repo_url)
        else:
            identity = mgr.resolve_identity(repo_url)

        async with GitHubClient(identity) as gh:
            connector = RepoConnector(
                gh, identity, repo_owner, repo_name,
                target_branch=target_branch,
            )
            push_result = await connector.push_pipeline_results(
                repo_path, pipeline_id, code_artifacts, pr_strategy,
            )

            # Report back to the triggering issue if set
            if issue_number:
                tracker = IssueTracker(gh, repo_owner, repo_name)
                pr_url = push_result["prs"][0] if push_result["prs"] else "N/A"
                total = len(code_artifacts)
                passed = sum(
                    1
                    for a in code_artifacts
                    if (a.get("qa_review") or {}).get("verdict") == "approved"
                )
                await tracker.report_to_issue(
                    issue_number,
                    pipeline_id,
                    {
                        "pr_url": pr_url,
                        "tickets_total": total,
                        "tickets_passed": passed,
                        "total_cost_usd": input.get("total_cost_usd", 0.0),
                        "duration": input.get("duration", "N/A"),
                    },
                )
                await tracker.update_issue_status(
                    issue_number, "PR created", f"PR: {pr_url}",
                )

        elapsed = time.monotonic() - start
        pipeline_log.info(
            "results pushed",
            prs=len(push_result.get("prs", [])),
            branches=push_result.get("branches", []),
            duration_seconds=round(elapsed, 2),
        )
        return StageResult(
            stage=PipelineStage.MERGE,
            success=True,
            artifact={**push_result, "pushed": True},
            cost_usd=0.0,
            duration_seconds=round(elapsed, 2),
        )

    except ForgeError:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - start
        pipeline_log.error(
            "push_pipeline_results failed",
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_seconds=round(elapsed, 2),
        )
        error = _classify_and_wrap(
            exc,
            pipeline_id=pipeline_id,
            stage="merge",
            agent_role="push",
        )
        await _get_error_reporter().report(error)
        _raise_as_temporal(error)


# ---------------------------------------------------------------------------
# Activity registry (for worker registration)
# ---------------------------------------------------------------------------

ALL_ACTIVITIES = [
    run_business_analysis,
    run_research,
    run_architecture,
    run_task_decomposition,
    run_scaffold_project,
    run_validate_execution_order,
    run_coding_task,
    run_qa_review,
    run_merge,
    run_coding_group,
    run_integration_check,
    run_cto_intervention,
    emit_pipeline_event,
    initialize_pipeline_state,
    finalize_pipeline_state,
    extract_pipeline_lessons,
    store_agent_memory,
    clone_remote_repo,
    push_pipeline_results,
]
