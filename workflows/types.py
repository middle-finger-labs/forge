"""Workflow I/O types for Temporal serialization.

Plain dataclasses — NOT Pydantic — because Temporal's Python SDK uses its own
``DataConverter`` (default: JSON via ``dataclasses_json``).  Pydantic models
cannot be passed directly as workflow/activity arguments without a custom
converter.

These types define the exact shape of data crossing workflow ↔ activity
boundaries.  Domain validation stays in ``contracts.schemas``; these are
transport containers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PipelineStage(StrEnum):
    INTAKE = "intake"
    BUSINESS_ANALYSIS = "business_analysis"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    TASK_DECOMPOSITION = "task_decomposition"
    CODING = "coding"
    QA_REVIEW = "qa_review"
    MERGE = "merge"
    COMPLETE = "complete"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


# ---------------------------------------------------------------------------
# Pipeline-level I/O
# ---------------------------------------------------------------------------


@dataclass
class PipelineInput:
    """Top-level input to kick off a full pipeline run."""

    pipeline_id: str = field(default_factory=lambda: uuid4().hex)
    business_spec: str = ""
    project_name: str = ""
    config_overrides: dict[str, Any] = field(default_factory=dict)

    # --- Multi-tenant org context ---
    org_id: str = ""

    # --- GitHub repo integration (all optional) ---
    repo_url: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None
    git_identity_name: str | None = None
    issue_number: int | None = None
    target_branch: str = "main"
    pr_strategy: str = "single_pr"


@dataclass
class StageResult:
    """Result of a single pipeline stage (activity return value)."""

    stage: PipelineStage = PipelineStage.INTAKE
    success: bool = False
    artifact: dict[str, Any] | None = None
    error: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Human-in-the-loop
# ---------------------------------------------------------------------------


@dataclass
class HumanApproval:
    """Signal payload sent when a human approves/rejects a stage artifact."""

    stage: PipelineStage = PipelineStage.INTAKE
    status: ApprovalStatus = ApprovalStatus.PENDING
    notes: str = ""
    approved_by: str = ""


@dataclass
class RetryStageRequest:
    """Signal payload to retry a failed stage with optional modified input."""

    stage: PipelineStage = PipelineStage.INTAKE
    modified_input: dict[str, Any] = field(default_factory=dict)
    requested_by: str = ""


# ---------------------------------------------------------------------------
# Coding stage I/O
# ---------------------------------------------------------------------------


@dataclass
class CodingTaskInput:
    """Input to a single ticket-level coding activity."""

    pipeline_id: str = ""
    ticket: dict[str, Any] = field(default_factory=dict)
    tech_spec_context: dict[str, Any] = field(default_factory=dict)
    worktree_path: str = ""
    branch_name: str = ""
    repo_path: str = ""
    reuse_worktree: bool = False
    org_id: str = ""
    codebase_context: str = ""


@dataclass
class CodingTaskResult:
    """Output of a single ticket-level coding activity."""

    ticket_id: str = ""
    success: bool = False
    code_artifact: dict[str, Any] | None = None
    error: str | None = None
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# QA stage I/O
# ---------------------------------------------------------------------------


@dataclass
class QATaskInput:
    """Input to a single ticket-level QA review activity."""

    pipeline_id: str = ""
    ticket: dict[str, Any] = field(default_factory=dict)
    code_artifact: dict[str, Any] = field(default_factory=dict)
    coding_standards: list[str] = field(default_factory=list)
    codebase_context: str = ""


@dataclass
class QATaskResult:
    """Output of a single ticket-level QA review activity."""

    ticket_id: str = ""
    verdict: str = ""
    review: dict[str, Any] | None = None
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Group-level coding I/O (one execution_order group)
# ---------------------------------------------------------------------------


@dataclass
class GroupTaskInput:
    """Input to a group-level coding activity.

    Encapsulates an entire execution_order group so that coding, QA, and
    merge can all happen within a single Temporal activity using asyncio
    concurrency.
    """

    pipeline_id: str = ""
    group_index: int = 0
    tickets: list[dict[str, Any]] = field(default_factory=list)
    tech_spec: dict[str, Any] = field(default_factory=dict)
    tech_spec_context: dict[str, Any] = field(default_factory=dict)
    repo_path: str = ""
    coding_standards: list[str] = field(default_factory=list)
    org_id: str = ""
    repo_url: str = ""


@dataclass
class GroupTaskResult:
    """Output of a group-level coding activity."""

    group_index: int = 0
    ticket_results: list[dict[str, Any]] = field(default_factory=list)
    qa_results: list[dict[str, Any]] = field(default_factory=list)
    merge_result: dict[str, Any] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    failed_tickets: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    communication_cost_usd: float = 0.0
    agent_exchanges: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PipelineEvent:
    """Broadcast event emitted at every significant pipeline transition."""

    pipeline_id: str = ""
    event_type: str = ""
    agent_role: str | None = None
    agent_id: str | None = None
    stage: PipelineStage | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now)
