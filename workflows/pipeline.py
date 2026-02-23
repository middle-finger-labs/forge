"""Main Temporal workflow orchestrating the full Forge pipeline.

Stages execute sequentially with human approval gates, parallel coding
fan-out, and iterative QA review loops.  All state is queryable and the
pipeline can be aborted or paused via signals at any point.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from workflows.types import (
        ApprovalStatus,
        CodingTaskInput,
        CodingTaskResult,
        GroupTaskInput,
        GroupTaskResult,
        HumanApproval,
        PipelineEvent,
        PipelineInput,
        PipelineStage,
        QATaskInput,
        QATaskResult,
        RetryStageRequest,
        StageResult,
    )


# ---------------------------------------------------------------------------
# Activity names (defined in activities/, registered on workers)
# ---------------------------------------------------------------------------

ACT_BUSINESS_ANALYSIS = "run_business_analysis"
ACT_RESEARCH = "run_research"
ACT_ARCHITECTURE = "run_architecture"
ACT_TASK_DECOMPOSITION = "run_task_decomposition"
ACT_CODING = "run_coding_task"
ACT_QA_REVIEW = "run_qa_review"
ACT_MERGE = "run_merge"
ACT_CTO_INTERVENTION = "run_cto_intervention"
ACT_SCAFFOLD_PROJECT = "run_scaffold_project"
ACT_VALIDATE_EXECUTION_ORDER = "run_validate_execution_order"
ACT_CODING_GROUP = "run_coding_group"
ACT_INTEGRATION_CHECK = "run_integration_check"
ACT_EMIT_EVENT = "emit_pipeline_event"
ACT_INITIALIZE_STATE = "initialize_pipeline_state"
ACT_FINALIZE_STATE = "finalize_pipeline_state"
ACT_EXTRACT_LESSONS = "extract_pipeline_lessons"
ACT_STORE_MEMORY = "store_agent_memory"
ACT_CLONE_REMOTE_REPO = "clone_remote_repo"
ACT_PUSH_PIPELINE_RESULTS = "push_pipeline_results"

# ---------------------------------------------------------------------------
# Task queues
# ---------------------------------------------------------------------------

PIPELINE_QUEUE = "forge-pipeline"
CODING_QUEUE = "forge-coding"

# ---------------------------------------------------------------------------
# Retry policies
# ---------------------------------------------------------------------------

_NON_RETRYABLE = [
    "ContentPolicyError",
    "BudgetExceededError",
    "ValidationError",
    "PermissionDenied",
    "ContentPolicy",
    "BudgetExceeded",
]

# Single-attempt policy: activities now raise typed errors that the workflow
# handles via its own retry loop in _run_stage.
NO_RETRY = RetryPolicy(maximum_attempts=1)

STANDARD_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    non_retryable_error_types=_NON_RETRYABLE,
)

AGGRESSIVE_RETRY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    non_retryable_error_types=_NON_RETRYABLE,
)

# ---------------------------------------------------------------------------
# Stage timeout defaults (seconds)
# ---------------------------------------------------------------------------

_STAGE_TIMEOUTS: dict[PipelineStage, int] = {
    PipelineStage.BUSINESS_ANALYSIS: 300,
    PipelineStage.RESEARCH: 600,
    PipelineStage.ARCHITECTURE: 300,
    PipelineStage.TASK_DECOMPOSITION: 600,
    PipelineStage.CODING: 900,
    PipelineStage.QA_REVIEW: 300,
    PipelineStage.MERGE: 120,
}


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@workflow.defn
class ForgePipeline:
    """Orchestrates spec → research → arch → tickets → code → QA → merge."""

    # -- state --
    pipeline_id: str = ""
    current_stage: PipelineStage = PipelineStage.INTAKE
    total_cost_usd: float = 0.0
    max_cost_usd: float = 50.0

    product_spec: dict | None = None
    enriched_spec: dict | None = None
    tech_spec: dict | None = None
    prd_board: dict | None = None

    code_artifacts: list[dict] = []
    qa_reviews: list[dict] = []

    pending_approval: PipelineStage | None = None
    approval_received: HumanApproval | None = None
    aborted: bool = False
    abort_reason: str = ""
    repo_path: str = ""
    _model_downgraded: bool = False

    # -----------------------------------------------------------------------
    # Signals
    # -----------------------------------------------------------------------

    @workflow.signal
    async def human_approval(self, approval: HumanApproval) -> None:
        """Receive a human approval/rejection for a pending stage."""
        self.approval_received = approval

    @workflow.signal
    async def abort(self, reason: str) -> None:
        """Abort the pipeline immediately."""
        self.aborted = True
        self.abort_reason = reason

    _retry_request: RetryStageRequest | None = None

    @workflow.signal
    async def retry_stage(self, request: RetryStageRequest) -> None:
        """Request a retry of a failed stage (sent from the admin API)."""
        self._retry_request = request

    # -----------------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------------

    @workflow.query
    def get_state(self) -> dict:
        """Return a snapshot of the full pipeline state."""
        return {
            "pipeline_id": self.pipeline_id,
            "current_stage": self.current_stage,
            "total_cost_usd": self.total_cost_usd,
            "max_cost_usd": self.max_cost_usd,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "pending_approval": self.pending_approval,
            "product_spec": self.product_spec,
            "enriched_spec": self.enriched_spec,
            "tech_spec": self.tech_spec,
            "prd_board": self.prd_board,
            "repo_path": self.repo_path,
            "code_artifacts": list(self.code_artifacts),
            "qa_reviews": list(self.qa_reviews),
            "model_downgraded": self._model_downgraded,
        }

    @workflow.query
    def get_cost(self) -> float:
        """Return total spend so far."""
        return self.total_cost_usd

    # -----------------------------------------------------------------------
    # Main run
    # -----------------------------------------------------------------------

    @workflow.run
    async def run(self, input: PipelineInput) -> dict:
        """Execute the full pipeline: BA → approval → Research → Arch →
        approval → PM → coding swarm → merge → complete."""

        # Initialise mutable state (class-level defaults are shared across
        # instances in the same worker, so reset here).
        self.pipeline_id = input.pipeline_id
        self.org_id = input.org_id or ""
        self.current_stage = PipelineStage.INTAKE
        self.total_cost_usd = 0.0
        self.max_cost_usd = float(
            input.config_overrides.get("max_cost_usd", 50.0)  # type: ignore[arg-type]
        )
        self.product_spec = None
        self.enriched_spec = None
        self.tech_spec = None
        self.prd_board = None
        self.code_artifacts = []
        self.qa_reviews = []
        self.pending_approval = None
        self.approval_received = None
        self.aborted = False
        self.abort_reason = ""
        self.repo_path = ""
        self._model_downgraded = False

        # Reset the budget manager singleton for this run
        try:
            from config.budget import reset_budget_manager

            reset_budget_manager()
        except Exception:
            pass

        # Persist initial pipeline state to PostgreSQL
        await workflow.execute_activity(
            ACT_INITIALIZE_STATE,
            {
                "pipeline_id": self.pipeline_id,
                "org_id": self.org_id,
                "business_spec": input.business_spec,
                "project_name": input.project_name,
            },
            task_queue=PIPELINE_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        await self._emit_event("pipeline.started", stage=PipelineStage.INTAKE)

        try:
            # Stage 1 — Business Analysis
            result = await self._run_stage(
                PipelineStage.BUSINESS_ANALYSIS,
                ACT_BUSINESS_ANALYSIS,
                {
                    "pipeline_id": self.pipeline_id,
                    "org_id": self.org_id,
                    "business_spec": input.business_spec,
                    "project_name": input.project_name,
                },
            )
            self.product_spec = result.artifact

            # Human approval gate (BA)
            await self._wait_for_approval(PipelineStage.BUSINESS_ANALYSIS)

            # Stage 2 — Research
            result = await self._run_stage(
                PipelineStage.RESEARCH,
                ACT_RESEARCH,
                {"pipeline_id": self.pipeline_id, "org_id": self.org_id, "product_spec": self.product_spec},
            )
            self.enriched_spec = result.artifact

            # Stage 3 — Architecture
            result = await self._run_stage(
                PipelineStage.ARCHITECTURE,
                ACT_ARCHITECTURE,
                {"pipeline_id": self.pipeline_id, "org_id": self.org_id, "enriched_spec": self.enriched_spec},
            )
            self.tech_spec = result.artifact

            # Human approval gate (Architecture)
            await self._wait_for_approval(PipelineStage.ARCHITECTURE)

            # Stage 4 — Task Decomposition
            result = await self._run_stage(
                PipelineStage.TASK_DECOMPOSITION,
                ACT_TASK_DECOMPOSITION,
                {
                    "pipeline_id": self.pipeline_id,
                    "org_id": self.org_id,
                    "tech_spec": self.tech_spec,
                    "enriched_spec": self.enriched_spec,
                },
            )
            self.prd_board = result.artifact

            # Stage 4b — Project Scaffold (or clone remote repo)
            if input.repo_url:
                scaffold_result = await self._run_stage(
                    PipelineStage.TASK_DECOMPOSITION,
                    ACT_CLONE_REMOTE_REPO,
                    {
                        "pipeline_id": self.pipeline_id,
                        "org_id": self.org_id,
                        "repo_url": input.repo_url,
                        "repo_owner": input.repo_owner or "",
                        "repo_name": input.repo_name or "",
                        "git_identity_name": input.git_identity_name,
                        "tech_spec": self.tech_spec,
                        "target_branch": input.target_branch,
                    },
                )
            else:
                scaffold_result = await self._run_stage(
                    PipelineStage.TASK_DECOMPOSITION,
                    ACT_SCAFFOLD_PROJECT,
                    {
                        "pipeline_id": self.pipeline_id,
                        "org_id": self.org_id,
                        "tech_spec": self.tech_spec,
                        "project_name": input.project_name,
                    },
                )
            self.repo_path = (scaffold_result.artifact or {}).get("repo_path", "")
            await self._emit_event(
                "scaffold.completed",
                stage=PipelineStage.TASK_DECOMPOSITION,
                payload={"repo_path": self.repo_path},
            )

            # Stage 4c — Validate & optimise execution order
            await self._validate_execution_order()

            # Stage 5+6+7 — Coding groups (coding + QA + merge per group)
            await self._run_coding_swarm()

            # Integration check — full test suite on merged main
            await self._run_integration_check()

            # Push to GitHub if this is a remote repo pipeline
            if input.repo_url and self.repo_path:
                await self._emit_event(
                    "github.push_started",
                    stage=PipelineStage.MERGE,
                    payload={"strategy": input.pr_strategy},
                )
                push_result = await self._run_stage(
                    PipelineStage.MERGE,
                    ACT_PUSH_PIPELINE_RESULTS,
                    {
                        "pipeline_id": self.pipeline_id,
                        "org_id": self.org_id,
                        "repo_path": self.repo_path,
                        "repo_owner": input.repo_owner or "",
                        "repo_name": input.repo_name or "",
                        "git_identity_name": input.git_identity_name,
                        "repo_url": input.repo_url,
                        "pr_strategy": input.pr_strategy,
                        "code_artifacts": self.code_artifacts,
                        "issue_number": input.issue_number,
                        "project_name": input.project_name,
                        "total_cost_usd": self.total_cost_usd,
                        "target_branch": input.target_branch,
                    },
                )
                await self._emit_event(
                    "github.push_completed",
                    stage=PipelineStage.MERGE,
                    payload=push_result.artifact or {},
                )

            self.current_stage = PipelineStage.COMPLETE
            await self._emit_event("pipeline.completed", stage=PipelineStage.COMPLETE)

            # Extract lessons from the completed pipeline for future runs
            await self._extract_lessons()

            # Persist terminal status
            await self._finalize_state("completed")

            return self.get_state()

        except Exception as exc:
            self.current_stage = PipelineStage.FAILED
            await self._emit_event(
                "pipeline.failed",
                stage=PipelineStage.FAILED,
                payload={"error": str(exc)},
            )

            # Persist terminal status
            status = "aborted" if self.aborted else "failed"
            await self._finalize_state(status)

            raise

    # -----------------------------------------------------------------------
    # Stage runner
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_error_details(app_err: ApplicationError) -> dict:
        """Extract structured error info from an ApplicationError.

        Tries ``app_err.details[0]`` (the dict from ForgeError.to_dict()),
        falls back to matching ``app_err.type`` against known class names.
        """
        # 1. Try to get the serialised ForgeError dict from details
        try:
            if app_err.details and len(app_err.details) > 0:
                detail = app_err.details[0]
                if isinstance(detail, dict) and "error_type" in detail:
                    return detail
        except Exception:
            pass

        # 2. Fall back to the ApplicationError.type field
        error_type = getattr(app_err, "type", None) or "unknown"
        non_retryable = getattr(app_err, "non_retryable", False)

        return {
            "error_type": error_type,
            "is_retryable": not non_retryable,
            "message": str(app_err),
        }

    async def _run_stage(
        self,
        stage: PipelineStage,
        activity_name: str,
        activity_input: dict,
        *,
        task_queue: str = PIPELINE_QUEUE,
        max_retries: int = 3,
    ) -> StageResult:
        """Execute a single pipeline stage with budget check, event emission,
        and type-aware retry logic."""

        budget_status = self._check_budget(stage)

        # Hard stop at 100 %
        if budget_status["hard_stop"]:
            await self._emit_event(
                "cost.kill_switch",
                stage=stage,
                payload=self._budget_payload(budget_status),
            )
            raise ApplicationError(
                budget_status["message"],
                non_retryable=True,
            )

        # 80 % alert — switch to cheaper models
        if budget_status["alert"] and not self._model_downgraded:
            self._model_downgraded = True
            await self._emit_event(
                "cost.alert",
                stage=stage,
                payload={
                    **self._budget_payload(budget_status),
                    "action": "model_downgrade",
                },
            )

        # 50 % warning
        if budget_status["warning"] and not budget_status["alert"]:
            await self._emit_event(
                "cost.warning",
                stage=stage,
                payload=self._budget_payload(budget_status),
            )

        # Abort guard
        if self.aborted:
            raise ApplicationError(
                f"Pipeline aborted: {self.abort_reason}",
                non_retryable=True,
            )

        self.current_stage = stage
        await self._emit_event("stage.started", stage=stage)
        timeout = _STAGE_TIMEOUTS.get(stage, 300)
        last_error = ""

        for attempt in range(1, max_retries + 1):
            try:
                result: StageResult = await workflow.execute_activity(
                    activity_name,
                    activity_input,
                    result_type=StageResult,
                    task_queue=task_queue,
                    schedule_to_close_timeout=timedelta(seconds=timeout),
                    retry_policy=NO_RETRY,
                )

                self.total_cost_usd += result.cost_usd

                # Legacy path: activity returned error instead of raising
                if not result.success:
                    raise ApplicationError(
                        f"Stage {stage} failed: {result.error or 'unknown error'}",
                        non_retryable=True,
                    )

                await self._emit_event(
                    "stage.completed",
                    stage=stage,
                    payload={
                        "cost_usd": result.cost_usd,
                        "duration_seconds": result.duration_seconds,
                    },
                )
                return result

            except ActivityError as act_err:
                # Temporal wraps activity failures in ActivityError;
                # the original ApplicationError is in .cause.
                app_err = act_err.cause
                if isinstance(app_err, ApplicationError):
                    error_info = self._parse_error_details(app_err)
                else:
                    error_info = {
                        "error_type": "unknown",
                        "is_retryable": True,
                        "message": str(act_err),
                    }
                error_type = error_info.get("error_type", "unknown")
                last_error = str(act_err)

                await self._emit_event(
                    "stage.error",
                    stage=stage,
                    payload={
                        "error_type": error_type,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "is_retryable": error_info.get("is_retryable"),
                        "message": last_error[:500],
                    },
                )

                # -- Non-retryable: fail immediately --
                if error_type == "BudgetExceededError":
                    raise
                if error_type == "ContentPolicyError":
                    raise
                if not error_info.get("is_retryable", False):
                    raise
                if attempt >= max_retries:
                    break

                # -- Type-specific retry strategies --
                if error_type == "AgentTimeoutError":
                    timeout = int(timeout * 1.5)
                    if attempt >= 2 and not self._model_downgraded:
                        self._model_downgraded = True
                        await self._emit_event("error.model_downgrade", stage=stage)

                elif error_type == "LLMError":
                    category = error_info.get("error_category", "unknown")
                    delay = {
                        "rate_limit": min(30, 5 * attempt),
                        "server_error": min(60, 10 * attempt),
                    }.get(category, 2 * attempt)
                    await workflow.sleep(timedelta(seconds=delay))

                elif error_type == "ValidationError":
                    activity_input = {
                        **activity_input,
                        "_validation_retry": True,
                        "_validation_errors": error_info.get("validation_errors", []),
                    }

                elif error_type in ("GitError", "MergeConflictError"):
                    if attempt >= 2:
                        # Escalate to CTO after second git failure
                        break
                    await workflow.sleep(timedelta(seconds=5))

        raise ApplicationError(
            f"Stage {stage} failed after {max_retries} attempts: {last_error}",
            non_retryable=True,
        )

    # -----------------------------------------------------------------------
    # Execution order validation (Stage 4c)
    # -----------------------------------------------------------------------

    async def _validate_execution_order(self) -> None:
        """Validate the PM's execution_order and auto-fix if possible.

        On failure, escalates to the CTO agent for a decision (abort,
        continue with the optimised order, or pause for human review).
        """
        assert self.prd_board is not None

        await self._emit_event(
            "validation.started",
            stage=PipelineStage.TASK_DECOMPOSITION,
        )

        validation_result: StageResult = await workflow.execute_activity(
            ACT_VALIDATE_EXECUTION_ORDER,
            {
                "pipeline_id": self.pipeline_id,
                "prd_board": self.prd_board,
                "tech_spec": self.tech_spec,
            },
            result_type=StageResult,
            task_queue=PIPELINE_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=60),
            retry_policy=STANDARD_RETRY,
        )

        artifact = validation_result.artifact or {}
        updated_board = artifact.get("prd_board", self.prd_board)
        was_optimised = artifact.get("optimised", False)

        if validation_result.success:
            # Apply the (possibly optimised) board
            self.prd_board = updated_board
            payload = {"optimised": was_optimised}
            if was_optimised:
                payload["original_errors"] = artifact.get(
                    "original_errors",
                    [],
                )
            await self._emit_event(
                "validation.passed",
                stage=PipelineStage.TASK_DECOMPOSITION,
                payload=payload,
            )
            return

        # Validation failed even after auto-fix — escalate to CTO
        remaining_errors = artifact.get("validation_errors", [])

        await self._emit_event(
            "validation.failed",
            stage=PipelineStage.TASK_DECOMPOSITION,
            payload={"errors": remaining_errors},
        )

        cto_result: StageResult = await workflow.execute_activity(
            ACT_CTO_INTERVENTION,
            {
                "trigger_type": "execution_order_invalid",
                "trigger_description": (
                    "Execution order validation failed after auto-fix: "
                    + "; ".join(remaining_errors[:5])
                ),
                "pipeline_state": self.get_state(),
                "context": {
                    "validation_errors": remaining_errors,
                    "prd_board": updated_board,
                },
            },
            result_type=StageResult,
            task_queue=PIPELINE_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=300),
            retry_policy=STANDARD_RETRY,
        )
        self.total_cost_usd += cto_result.cost_usd

        decision = cto_result.artifact or {}
        action = decision.get("pipeline_action", "continue")

        if action == "abort":
            self.aborted = True
            self.abort_reason = decision.get(
                "rationale",
                "CTO aborted due to invalid execution order",
            )
            raise ApplicationError(
                f"Pipeline aborted by CTO: {self.abort_reason}",
                non_retryable=True,
            )

        if action == "pause":
            await self._wait_for_approval(PipelineStage.TASK_DECOMPOSITION)

        # "continue" or "retry_ticket" — use the best-effort board
        self.prd_board = updated_board
        await self._emit_event(
            "validation.overridden",
            stage=PipelineStage.TASK_DECOMPOSITION,
            payload={"cto_action": action},
        )

    # -----------------------------------------------------------------------
    # Coding swarm (Stage 5 + 6 + 7 per group)
    # -----------------------------------------------------------------------

    async def _run_coding_swarm(self) -> None:
        """Iterate execution_order groups, dispatching each as a single
        ``run_coding_group`` activity that handles coding, QA, and merge
        internally via asyncio parallelism.

        Failed tickets within a group do not block the pipeline — they
        are reported in the group result and the pipeline continues.
        """

        assert self.prd_board is not None, "prd_board must be set before coding"
        assert self.tech_spec is not None, "tech_spec must be set before coding"

        self.current_stage = PipelineStage.CODING

        tickets_by_key: dict[str, dict] = {t["ticket_key"]: t for t in self.prd_board["tickets"]}
        execution_order: list[list[str]] = self.prd_board["execution_order"]
        coding_standards: list[str] = self.tech_spec.get("coding_standards", [])

        for group_idx, group in enumerate(execution_order):
            if self.aborted:
                raise ApplicationError(
                    f"Pipeline aborted: {self.abort_reason}",
                    non_retryable=True,
                )

            # Budget guard
            budget_status = self._check_budget(PipelineStage.CODING)
            if budget_status["hard_stop"]:
                await self._emit_event(
                    "cost.kill_switch",
                    stage=PipelineStage.CODING,
                    payload=self._budget_payload(budget_status),
                )
                raise ApplicationError(
                    budget_status["message"],
                    non_retryable=True,
                )
            if budget_status["alert"] and not self._model_downgraded:
                self._model_downgraded = True
                await self._emit_event(
                    "cost.alert",
                    stage=PipelineStage.CODING,
                    payload={
                        **self._budget_payload(budget_status),
                        "action": "model_downgrade",
                    },
                )

            group_tickets = [tickets_by_key[tk] for tk in group]

            await self._emit_event(
                "group.started",
                stage=PipelineStage.CODING,
                payload={
                    "group_index": group_idx,
                    "ticket_keys": group,
                },
            )

            group_input = GroupTaskInput(
                pipeline_id=self.pipeline_id,
                group_index=group_idx,
                tickets=group_tickets,
                tech_spec=self.tech_spec,
                tech_spec_context=self.tech_spec,
                repo_path=self.repo_path,
                coding_standards=coding_standards,
                org_id=self.org_id,
            )

            # Each group runs as a single activity: coding + QA + merge.
            # Retry up to 2 attempts; on failure, emit group.failed and
            # continue to the next group (don't abort the pipeline).
            group_timeout = _STAGE_TIMEOUTS[PipelineStage.CODING] * len(group)
            group_result: GroupTaskResult | None = None
            max_group_attempts = 2

            for g_attempt in range(1, max_group_attempts + 1):
                try:
                    group_result = await workflow.execute_activity(
                        ACT_CODING_GROUP,
                        group_input,
                        result_type=GroupTaskResult,
                        task_queue=CODING_QUEUE,
                        schedule_to_close_timeout=timedelta(seconds=group_timeout),
                        retry_policy=NO_RETRY,
                    )
                    break  # success
                except ActivityError as grp_act_err:
                    grp_cause = grp_act_err.cause
                    if isinstance(grp_cause, ApplicationError):
                        error_info = self._parse_error_details(grp_cause)
                    else:
                        error_info = {
                            "error_type": "unknown",
                            "is_retryable": True,
                        }
                    if not error_info.get("is_retryable", False):
                        await self._emit_event(
                            "group.failed",
                            stage=PipelineStage.CODING,
                            payload={
                                "group_index": group_idx,
                                "error_type": error_info.get("error_type"),
                                "message": str(grp_act_err)[:500],
                            },
                        )
                        break
                    if g_attempt >= max_group_attempts:
                        await self._emit_event(
                            "group.failed",
                            stage=PipelineStage.CODING,
                            payload={
                                "group_index": group_idx,
                                "error_type": error_info.get("error_type"),
                                "message": str(grp_act_err)[:500],
                                "attempts_exhausted": True,
                            },
                        )
                        break
                    await self._emit_event(
                        "stage.error",
                        stage=PipelineStage.CODING,
                        payload={
                            "error_type": error_info.get("error_type"),
                            "attempt": g_attempt,
                            "max_retries": max_group_attempts,
                            "group_index": group_idx,
                        },
                    )
                    await workflow.sleep(timedelta(seconds=5))

            if group_result is None:
                continue  # group failed, move on

            self.total_cost_usd += group_result.total_cost_usd

            # Collect artifacts from successful tickets
            for tr in group_result.ticket_results:
                if tr.get("success") and tr.get("code_artifact"):
                    self.code_artifacts.append(tr["code_artifact"])

            # Collect QA reviews
            for qr in group_result.qa_results:
                if qr.get("review"):
                    self.qa_reviews.append(qr["review"])

            await self._emit_event(
                "group.completed",
                stage=PipelineStage.CODING,
                payload={
                    "group_index": group_idx,
                    "merged": group_result.merge_result.get("merged", []),
                    "failed_tickets": group_result.failed_tickets,
                    "cost_usd": group_result.total_cost_usd,
                    "duration_seconds": group_result.duration_seconds,
                },
            )

            # Log warnings for failed tickets (non-fatal)
            if group_result.failed_tickets:
                await self._emit_event(
                    "tickets.failed",
                    stage=PipelineStage.CODING,
                    payload={
                        "group_index": group_idx,
                        "failed_tickets": group_result.failed_tickets,
                    },
                )

    # -----------------------------------------------------------------------
    # Integration check (post-merge)
    # -----------------------------------------------------------------------

    async def _run_integration_check(self) -> None:
        """Run the full test suite on the merged main branch after all
        groups have been processed.
        """
        self.current_stage = PipelineStage.MERGE

        await self._emit_event("integration_check.started", stage=PipelineStage.MERGE)

        result: StageResult = await workflow.execute_activity(
            ACT_INTEGRATION_CHECK,
            {
                "pipeline_id": self.pipeline_id,
                "repo_path": self.repo_path,
            },
            result_type=StageResult,
            task_queue=CODING_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=600),
            retry_policy=STANDARD_RETRY,
        )

        self.total_cost_usd += result.cost_usd

        if result.success:
            await self._emit_event(
                "integration_check.passed",
                stage=PipelineStage.MERGE,
                payload={"duration_seconds": result.duration_seconds},
            )
        else:
            await self._emit_event(
                "integration_check.failed",
                stage=PipelineStage.MERGE,
                payload={
                    "error": result.error or "Tests failed",
                    "duration_seconds": result.duration_seconds,
                },
            )
            # Integration failure is non-fatal — logged as warning
            workflow.logger.warning(
                "Integration check failed for pipeline %s: %s",
                self.pipeline_id,
                result.error,
            )

    # -----------------------------------------------------------------------
    # QA review loop
    # -----------------------------------------------------------------------

    async def _qa_review_loop(
        self,
        ticket: dict,
        code_artifact: dict,
        coding_standards: list[str],
        max_revisions: int = 3,
    ) -> bool:
        """Run QA → revision cycles up to *max_revisions* times.

        When revisions are exhausted or a "rejected" verdict is received,
        the CTO agent is invoked to decide the next action (retry, skip,
        pause, or abort).

        Returns True if ultimately approved, False if skipped/continued.
        Raises ``ApplicationError`` if the CTO decides to abort.
        """
        ticket_key = ticket.get("ticket_key", "unknown")
        current_artifact = code_artifact
        ticket_qa_history: list[dict] = []

        for attempt in range(1, max_revisions + 1):
            self.current_stage = PipelineStage.QA_REVIEW

            qa_input = QATaskInput(
                pipeline_id=self.pipeline_id,
                ticket=ticket,
                code_artifact=current_artifact,
                coding_standards=coding_standards,
            )

            qa_result: QATaskResult = await workflow.execute_activity(
                ACT_QA_REVIEW,
                qa_input,
                result_type=QATaskResult,
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(
                    seconds=_STAGE_TIMEOUTS[PipelineStage.QA_REVIEW],
                ),
                retry_policy=STANDARD_RETRY,
            )
            self.total_cost_usd += qa_result.cost_usd

            review = qa_result.review or {}
            self.qa_reviews.append(review)
            ticket_qa_history.append(
                {
                    "attempt": attempt,
                    "verdict": qa_result.verdict,
                    "review": review,
                }
            )

            await self._emit_event(
                "qa.verdict",
                stage=PipelineStage.QA_REVIEW,
                payload={
                    "ticket_key": ticket_key,
                    "verdict": qa_result.verdict,
                    "attempt": attempt,
                },
            )

            if qa_result.verdict == "approved":
                return True

            # "rejected" — escalate to CTO immediately
            if qa_result.verdict == "rejected":
                # Store the rejection reason as a lesson for engineers
                await self._store_qa_lesson(ticket_key, review, attempt)

                cto_handled = await self._invoke_cto(
                    trigger_type="qa_rejected",
                    trigger_description=(
                        f"Ticket {ticket_key} was rejected by QA on "
                        f"attempt {attempt}: "
                        f"{review.get('revision_instructions', 'no details')}"
                    ),
                    ticket=ticket,
                    ticket_key=ticket_key,
                    current_artifact=current_artifact,
                    coding_standards=coding_standards,
                    qa_history=ticket_qa_history,
                )
                return cto_handled

            # needs_revision — check if auto-approve is appropriate
            comments = review.get("comments", [])
            has_serious = any(
                (c.get("severity") if isinstance(c, dict) else "") in ("error", "critical")
                for c in comments
            )

            if not has_serious and self._auto_approve_minor_only():
                await self._emit_event(
                    "qa.auto_approved",
                    stage=PipelineStage.QA_REVIEW,
                    payload={
                        "ticket_key": ticket_key,
                        "attempt": attempt,
                        "comment_count": len(comments),
                    },
                )
                return True

            # Store the lesson, then send back to coding
            await self._store_qa_lesson(ticket_key, review, attempt)

            if attempt < max_revisions:
                current_artifact = await self._run_revision(
                    ticket,
                    ticket_key,
                    review,
                    attempt,
                )
                if current_artifact is None:
                    # Revision coding failed — escalate to CTO
                    return await self._invoke_cto(
                        trigger_type="revision_coding_failed",
                        trigger_description=(
                            f"Revision coding for {ticket_key} failed on attempt {attempt}"
                        ),
                        ticket=ticket,
                        ticket_key=ticket_key,
                        current_artifact=code_artifact,
                        coding_standards=coding_standards,
                        qa_history=ticket_qa_history,
                    )

        # Exhausted all revision cycles — escalate to CTO
        return await self._invoke_cto(
            trigger_type="qa_revision_exhausted",
            trigger_description=(
                f"Ticket {ticket_key} has exhausted {max_revisions} QA "
                f"revision cycles without approval"
            ),
            ticket=ticket,
            ticket_key=ticket_key,
            current_artifact=current_artifact,
            coding_standards=coding_standards,
            qa_history=ticket_qa_history,
        )

    # -----------------------------------------------------------------------
    # Revision helper
    # -----------------------------------------------------------------------

    async def _run_revision(
        self,
        ticket: dict,
        ticket_key: str,
        review: dict,
        attempt: int,
    ) -> dict | None:
        """Send a ticket back to coding with revision instructions.

        Returns the new code artifact, or None if the revision failed.
        """
        self.current_stage = PipelineStage.CODING
        revision_input = CodingTaskInput(
            pipeline_id=self.pipeline_id,
            ticket={
                **ticket,
                "revision_instructions": review.get("revision_instructions", []),
                "previous_review": review,
            },
            tech_spec_context=self.tech_spec or {},
            worktree_path="",
            branch_name=f"forge/{ticket_key.lower()}/rev-{attempt}",
            repo_path=self.repo_path,
            reuse_worktree=True,
        )

        coding_result: CodingTaskResult = await workflow.execute_activity(
            ACT_CODING,
            revision_input,
            result_type=CodingTaskResult,
            task_queue=CODING_QUEUE,
            schedule_to_close_timeout=timedelta(
                seconds=_STAGE_TIMEOUTS[PipelineStage.CODING],
            ),
            retry_policy=AGGRESSIVE_RETRY,
        )
        self.total_cost_usd += coding_result.cost_usd

        if coding_result.success and coding_result.code_artifact:
            current_artifact = coding_result.code_artifact
            # Replace the last artifact with the revision
            for i in range(len(self.code_artifacts) - 1, -1, -1):
                if self.code_artifacts[i].get("ticket_key") == ticket_key:
                    self.code_artifacts[i] = current_artifact
                    break
            return current_artifact

        return None

    # -----------------------------------------------------------------------
    # CTO intervention
    # -----------------------------------------------------------------------

    async def _invoke_cto(
        self,
        *,
        trigger_type: str,
        trigger_description: str,
        ticket: dict,
        ticket_key: str,
        current_artifact: dict,
        coding_standards: list[str],
        qa_history: list[dict],
    ) -> bool:
        """Call the CTO intervention activity and act on its decision.

        Returns True if the ticket ends up approved (via CTO retry),
        False if skipped/continued.  Raises on abort.
        """
        await self._emit_event(
            "cto.intervention",
            stage=PipelineStage.QA_REVIEW,
            payload={
                "ticket_key": ticket_key,
                "trigger_type": trigger_type,
                "reason": trigger_description,
            },
        )

        cto_result: StageResult = await workflow.execute_activity(
            ACT_CTO_INTERVENTION,
            {
                "trigger_type": trigger_type,
                "trigger_description": trigger_description,
                "pipeline_state": self.get_state(),
                "context": {
                    "ticket": ticket,
                    "qa_history": qa_history,
                    "current_artifact": current_artifact,
                },
            },
            result_type=StageResult,
            task_queue=PIPELINE_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=300),
            retry_policy=STANDARD_RETRY,
        )
        self.total_cost_usd += cto_result.cost_usd

        decision = cto_result.artifact or {}
        action = decision.get("pipeline_action", "continue")

        # Store the CTO decision as a memory for future interventions
        await self._store_cto_decision_memory(
            ticket_key,
            trigger_type,
            decision,
        )

        # -- abort ----------------------------------------------------------
        if action == "abort":
            self.aborted = True
            self.abort_reason = decision.get("rationale", "CTO decided to abort the pipeline")
            raise ApplicationError(
                f"Pipeline aborted by CTO: {self.abort_reason}",
                non_retryable=True,
            )

        # -- pause (wait for human) -----------------------------------------
        if action == "pause":
            await self._emit_event(
                "human.approval_required",
                stage=PipelineStage.QA_REVIEW,
                payload={
                    "ticket_key": ticket_key,
                    "cto_decision": decision,
                },
            )
            await self._wait_for_approval(PipelineStage.QA_REVIEW)
            return True

        # -- retry_ticket ---------------------------------------------------
        if action == "retry_ticket":
            engineer_instructions = decision.get("instructions_to_engineer", "")
            retry_ticket = {
                **ticket,
                "cto_instructions": engineer_instructions,
                "revision_instructions": [engineer_instructions] if engineer_instructions else [],
            }

            # One more coding attempt with CTO guidance
            revised = await self._run_revision(
                retry_ticket,
                ticket_key,
                decision,
                attempt=0,
            )
            if revised is None:
                # Even CTO-guided revision failed — skip the ticket
                self._mark_ticket_skipped(ticket_key, decision)
                return False

            # One more QA pass
            qa_input = QATaskInput(
                pipeline_id=self.pipeline_id,
                ticket=retry_ticket,
                code_artifact=revised,
                coding_standards=coding_standards,
            )
            qa_instructions = decision.get("instructions_to_qa", "")
            if qa_instructions:
                qa_input.ticket = {
                    **qa_input.ticket,
                    "qa_focus": qa_instructions,
                }

            qa_result: QATaskResult = await workflow.execute_activity(
                ACT_QA_REVIEW,
                qa_input,
                result_type=QATaskResult,
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(
                    seconds=_STAGE_TIMEOUTS[PipelineStage.QA_REVIEW],
                ),
                retry_policy=STANDARD_RETRY,
            )
            self.total_cost_usd += qa_result.cost_usd

            review = qa_result.review or {}
            self.qa_reviews.append(review)

            if qa_result.verdict == "approved":
                return True

            # Still not approved after CTO retry — skip
            self._mark_ticket_skipped(ticket_key, decision)
            return False

        # -- continue (skip this ticket) ------------------------------------
        self._mark_ticket_skipped(ticket_key, decision)
        return False

    # -----------------------------------------------------------------------
    # Budget helpers
    # -----------------------------------------------------------------------

    def _check_budget(self, stage: PipelineStage | str = "") -> dict:
        """Return a budget status dict for the current pipeline state.

        Uses BudgetManager when available, falls back to inline calculation
        to stay compatible with the Temporal sandbox.
        """
        stage_str = str(stage) if stage else ""
        try:
            from config.budget import get_budget_manager

            bm = get_budget_manager(max_pipeline_cost=self.max_cost_usd)
            bm.max_pipeline_cost = self.max_cost_usd
            stage_cost = bm.get_stage_cost(stage_str)
            status = bm.check_budget(
                current_cost=self.total_cost_usd,
                current_stage=stage_str,
                stage_cost=stage_cost,
            )
            return {
                "total_budget": status.total_budget,
                "current_cost": status.current_cost,
                "remaining": status.remaining,
                "utilisation_pct": status.utilisation_pct,
                "warning": status.warning,
                "alert": status.alert,
                "hard_stop": status.hard_stop,
                "message": status.message,
            }
        except Exception:
            # Fallback: inline budget check (no BudgetManager dependency)
            remaining = max(self.max_cost_usd - self.total_cost_usd, 0.0)
            if self.max_cost_usd <= 0:
                pct = 100.0
            else:
                pct = self.total_cost_usd / self.max_cost_usd * 100
            over = self.total_cost_usd >= self.max_cost_usd
            return {
                "total_budget": self.max_cost_usd,
                "current_cost": self.total_cost_usd,
                "remaining": remaining,
                "utilisation_pct": round(pct, 1),
                "warning": pct >= 50,
                "alert": pct >= 80,
                "hard_stop": over,
                "message": (
                    f"Budget exceeded: ${self.total_cost_usd:.2f} / ${self.max_cost_usd:.2f}"
                ),
            }

    @staticmethod
    def _budget_payload(status: dict) -> dict:
        """Extract event payload fields from a budget status dict."""
        return {
            "total_budget": status.get("total_budget", 0),
            "current_cost": status.get("current_cost", 0),
            "remaining": status.get("remaining", 0),
            "utilisation_pct": status.get("utilisation_pct", 0),
            "message": status.get("message", ""),
        }

    def _auto_approve_minor_only(self) -> bool:
        """Check if auto-approve for minor-only reviews is enabled."""
        try:
            from config.agent_config import PIPELINE_CONFIG

            return PIPELINE_CONFIG.auto_approve_minor_only
        except Exception:
            return False

    def _mark_ticket_skipped(self, ticket_key: str, decision: dict) -> None:
        """Mark a ticket's artifact as skipped in code_artifacts."""
        for i in range(len(self.code_artifacts) - 1, -1, -1):
            if self.code_artifacts[i].get("ticket_key") == ticket_key:
                self.code_artifacts[i]["skipped"] = True
                self.code_artifacts[i]["skip_reason"] = decision.get(
                    "rationale", "Skipped after CTO intervention"
                )
                break

    # -----------------------------------------------------------------------
    # Human approval gate
    # -----------------------------------------------------------------------

    async def _wait_for_approval(self, stage: PipelineStage) -> None:
        """Block until a human approves the current stage artifact."""

        self.pending_approval = stage
        self.approval_received = None

        await self._emit_event("human.approval_required", stage=stage)

        # Block until signal arrives or pipeline is aborted
        await workflow.wait_condition(
            lambda: self.approval_received is not None or self.aborted,
        )

        self.pending_approval = None

        if self.aborted:
            raise ApplicationError(
                f"Pipeline aborted: {self.abort_reason}",
                non_retryable=True,
            )

        approval = self.approval_received
        assert approval is not None

        await self._emit_event(
            "human.approval_received",
            stage=stage,
            payload={
                "status": approval.status,
                "notes": approval.notes,
                "approved_by": approval.approved_by,
            },
        )

        if approval.status == ApprovalStatus.REJECTED:
            raise ApplicationError(
                f"Stage {stage} rejected by {approval.approved_by}: {approval.notes}",
                non_retryable=True,
            )

        if approval.status == ApprovalStatus.REVISION_REQUESTED:
            raise ApplicationError(
                f"Stage {stage} revision requested by {approval.approved_by}: {approval.notes}",
                non_retryable=True,
            )

        # ApprovalStatus.APPROVED — continue

    # -----------------------------------------------------------------------
    # State finalization helper
    # -----------------------------------------------------------------------

    async def _finalize_state(self, status: str) -> None:
        """Persist the terminal pipeline status to PostgreSQL."""
        try:
            await workflow.execute_activity(
                ACT_FINALIZE_STATE,
                {"pipeline_id": self.pipeline_id, "status": status},
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            workflow.logger.warning(
                "Failed to finalize pipeline state for %s",
                self.pipeline_id,
            )

    # -----------------------------------------------------------------------
    # Memory extraction helpers
    # -----------------------------------------------------------------------

    async def _extract_lessons(self) -> None:
        """Extract and store lessons from the completed pipeline run."""
        try:
            await workflow.execute_activity(
                ACT_EXTRACT_LESSONS,
                {
                    "pipeline_id": self.pipeline_id,
                    "pipeline_result": self.get_state(),
                    "org_id": self.org_id,
                },
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            workflow.logger.warning(
                "Failed to extract lessons for pipeline %s",
                self.pipeline_id,
            )

    async def _store_qa_lesson(
        self,
        ticket_key: str,
        review: dict,
        attempt: int,
    ) -> None:
        """Store a QA revision/rejection as a lesson for engineers."""
        revision_instructions = review.get("revision_instructions", [])
        comments = review.get("comments", [])
        verdict = review.get("verdict", "needs_revision")

        # Build a concise lesson from the QA feedback
        issues: list[str] = []
        for instr in revision_instructions[:3]:
            if isinstance(instr, str):
                issues.append(instr)
            elif isinstance(instr, dict):
                issues.append(instr.get("instruction", str(instr)))
        for comment in comments[:3]:
            if isinstance(comment, dict) and comment.get("severity") in (
                "error",
                "warning",
            ):
                issues.append(comment.get("comment", ""))

        if not issues:
            return

        issue_text = "; ".join(i for i in issues if i)
        content = f"QA {verdict} ticket {ticket_key} (attempt {attempt}): {issue_text}"

        try:
            await workflow.execute_activity(
                ACT_STORE_MEMORY,
                {
                    "pipeline_id": self.pipeline_id,
                    "org_id": self.org_id,
                    "agent_role": "developer",
                    "content": content,
                    "memory_type": "lesson",
                    "metadata": {
                        "source": "qa_review",
                        "ticket_key": ticket_key,
                        "verdict": verdict,
                        "attempt": attempt,
                    },
                },
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            workflow.logger.warning(
                "Failed to store QA lesson for %s",
                ticket_key,
            )

    async def _store_cto_decision_memory(
        self,
        ticket_key: str,
        trigger_type: str,
        decision: dict,
    ) -> None:
        """Store a CTO intervention decision for future reference."""
        cto_decision = decision.get("decision", "")
        rationale = decision.get("rationale", "")
        action = decision.get("pipeline_action", "continue")

        if not cto_decision:
            return

        content = f"CTO intervention ({trigger_type}) for {ticket_key}: {cto_decision}"

        try:
            await workflow.execute_activity(
                ACT_STORE_MEMORY,
                {
                    "pipeline_id": self.pipeline_id,
                    "org_id": self.org_id,
                    "agent_role": "cto",
                    "content": content,
                    "memory_type": "decision",
                    "decision_type": f"cto_{trigger_type}",
                    "rationale": rationale,
                    "metadata": {
                        "source": "cto_intervention",
                        "ticket_key": ticket_key,
                        "trigger_type": trigger_type,
                        "pipeline_action": action,
                    },
                },
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            workflow.logger.warning(
                "Failed to store CTO decision for %s",
                ticket_key,
            )

    # -----------------------------------------------------------------------
    # Event emission helper
    # -----------------------------------------------------------------------

    async def _emit_event(
        self,
        event_type: str,
        *,
        stage: PipelineStage | None = None,
        payload: dict | None = None,
    ) -> None:
        """Fire-and-forget event emission via a short-lived activity."""
        event = PipelineEvent(
            pipeline_id=self.pipeline_id,
            event_type=event_type,
            stage=stage,
            payload=payload or {},
        )
        try:
            await workflow.execute_activity(
                ACT_EMIT_EVENT,
                event,
                task_queue=PIPELINE_QUEUE,
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            # Event emission is best-effort; never block the pipeline
            workflow.logger.warning(
                "Failed to emit event %s for pipeline %s",
                event_type,
                self.pipeline_id,
            )
