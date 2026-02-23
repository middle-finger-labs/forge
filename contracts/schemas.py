"""Message contracts for inter-agent pipeline handoffs.

Every artifact passed between pipeline stages is validated against these schemas.
The pipeline flows:

  Stage 1 (PM)       → ProductSpec
  Stage 2 (Research) → EnrichedSpec
  Stage 3 (Arch)     → TechSpec
  Stage 4 (Tickets)  → PRDBoard
  Stage 5 (Dev)      → CodeArtifact
  Stage 6 (QA)       → QAReview
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Priority(StrEnum):
    """Task priority levels from critical to low."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TicketStatus(StrEnum):
    """Lifecycle states a ticket moves through from backlog to merged."""

    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    REVISION_NEEDED = "revision_needed"
    APPROVED = "approved"
    MERGED = "merged"


class TicketType(StrEnum):
    """Classification of work a ticket represents."""

    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    INFRASTRUCTURE = "infrastructure"
    TEST = "test"
    DOCUMENTATION = "documentation"
    REFACTOR = "refactor"


class QAVerdict(StrEnum):
    """Outcome of a QA review: approved, needs revision, or rejected."""

    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class AgentRole(StrEnum):
    """Identifiers for each specialized agent in the pipeline."""

    PRODUCT_MANAGER = "product_manager"
    RESEARCH_ANALYST = "research_analyst"
    ARCHITECT = "architect"
    TICKET_MANAGER = "ticket_manager"
    DEVELOPER = "developer"
    QA_ENGINEER = "qa_engineer"
    CTO = "cto"


# ---------------------------------------------------------------------------
# Stage 1 – Product Specification
# ---------------------------------------------------------------------------


class UserStory(BaseModel):
    """A single user story in standard persona/action/benefit format."""

    id: str = Field(pattern=r"^US-\d{3,}$", examples=["US-001"])
    persona: str = Field(min_length=1)
    action: str = Field(min_length=1)
    benefit: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    priority: Priority = Priority.MEDIUM
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of user stories this story depends on",
    )


class ProductSpec(BaseModel):
    """Stage 1 output: the product manager's specification."""

    spec_id: str
    product_name: str = Field(min_length=1)
    product_vision: str = Field(min_length=50)
    target_users: list[str] = Field(min_length=1)
    core_problem: str = Field(min_length=30)
    proposed_solution: str = Field(min_length=50)
    user_stories: list[UserStory] = Field(min_length=3)
    success_metrics: list[str] = Field(min_length=2)
    constraints: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("user_stories")
    @classmethod
    def unique_story_ids(cls, stories: list[UserStory]) -> list[UserStory]:
        """Validate that all user story IDs are unique within the spec."""
        ids = [s.id for s in stories]
        if len(ids) != len(set(ids)):
            dupes = {i for i in ids if ids.count(i) > 1}
            raise ValueError(f"Duplicate user story IDs: {dupes}")
        return stories


# ---------------------------------------------------------------------------
# Stage 2 – Research & Enrichment
# ---------------------------------------------------------------------------


class ResearchFinding(BaseModel):
    """A single research finding with source attribution and confidence score."""

    topic: str
    summary: str
    source: str = ""
    relevance: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class CompetitorAnalysis(BaseModel):
    """Competitive landscape entry capturing strengths, weaknesses, and differentiators."""

    name: str
    url: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)


class EnrichedSpec(BaseModel):
    """Stage 2 output: original spec enriched with research context."""

    original_spec: ProductSpec
    research_findings: list[ResearchFinding] = Field(default_factory=list)
    competitors: list[CompetitorAnalysis] = Field(default_factory=list)
    feasibility_notes: str = ""
    market_context: str = ""
    revised_questions: list[str] = Field(default_factory=list)
    recommended_changes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 3 – Technical Architecture
# ---------------------------------------------------------------------------

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


class APIEndpoint(BaseModel):
    """A single REST API endpoint with method, path, and auth metadata."""

    method: str
    path: str = Field(pattern=r"^/")
    description: str = ""
    request_body: str | None = None
    response_model: str | None = None
    auth_required: bool = True

    @field_validator("method")
    @classmethod
    def valid_http_method(cls, v: str) -> str:
        """Validate and upper-case the HTTP method against the allowed set."""
        upper = v.upper()
        if upper not in _HTTP_METHODS:
            raise ValueError(f"Invalid HTTP method '{v}', must be one of {sorted(_HTTP_METHODS)}")
        return upper


class DatabaseModel(BaseModel):
    """Schema definition for a single database table including columns and indexes."""

    name: str
    table_name: str
    columns: dict[str, str] = Field(
        description="Mapping of column name → type definition, e.g. {'id': 'UUID PRIMARY KEY'}",
    )
    indexes: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


class ServiceDefinition(BaseModel):
    """A microservice or component with its responsibility and API surface."""

    name: str
    responsibility: str
    endpoints: list[APIEndpoint] = Field(default_factory=list)
    dependencies: list[str] = Field(
        default_factory=list,
        description="Names of other services this service depends on",
    )


class TechSpec(BaseModel):
    """Stage 3 output: complete technical architecture."""

    spec_id: str
    services: list[ServiceDefinition] = Field(min_length=1)
    database_models: list[DatabaseModel] = Field(default_factory=list)
    api_endpoints: list[APIEndpoint] = Field(default_factory=list)
    tech_stack: dict[str, str] = Field(
        description="Category → technology, e.g. {'language': 'Python 3.12'}",
    )
    coding_standards: list[str] = Field(default_factory=list)
    file_structure: dict[str, str] = Field(
        default_factory=dict,
        description="Path → purpose, e.g. {'activities/fetch.py': 'HTTP fetch activity'}",
    )
    user_story_mapping: dict[str, list[str]] = Field(
        default_factory=dict,
        description="User story ID → list of service/component names that implement it",
    )


# ---------------------------------------------------------------------------
# Stage 4 – PRD / Ticket Board
# ---------------------------------------------------------------------------


class PRDTicket(BaseModel):
    """A single implementation ticket with file-level ownership."""

    ticket_key: str = Field(pattern=r"^FORGE-\d+$", examples=["FORGE-1"])
    title: str = Field(min_length=1)
    ticket_type: TicketType
    priority: Priority
    story_points: int = Field(ge=1, le=13)
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    files_owned: list[str] = Field(
        default_factory=list,
        description="File paths this ticket is responsible for creating/modifying",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Ticket keys this ticket depends on",
    )
    user_story_refs: list[str] = Field(
        default_factory=list,
        description="User story IDs this ticket implements",
    )
    status: TicketStatus = TicketStatus.BACKLOG


class PRDBoard(BaseModel):
    """Stage 4 output: the full ticket board with execution ordering."""

    board_id: str
    tickets: list[PRDTicket] = Field(min_length=1)
    execution_order: list[list[str]] = Field(
        min_length=1,
        description=(
            "Ordered list of parallel groups. Each group is a list of ticket keys "
            "that can execute concurrently. Groups run sequentially."
        ),
    )
    critical_path: list[str] = Field(
        default_factory=list,
        description="Ticket keys on the critical path, in execution order",
    )

    @model_validator(mode="after")
    def execution_order_covers_all_tickets(self) -> Self:
        """Validate that execution_order references exactly the set of ticket keys
        defined on the board -- no missing and no unknown keys.
        """
        ticket_keys = {t.ticket_key for t in self.tickets}
        ordered_keys = {key for group in self.execution_order for key in group}
        missing = ticket_keys - ordered_keys
        if missing:
            raise ValueError(f"execution_order is missing tickets: {sorted(missing)}")
        unknown = ordered_keys - ticket_keys
        if unknown:
            raise ValueError(f"execution_order references unknown tickets: {sorted(unknown)}")
        return self


# ---------------------------------------------------------------------------
# Stage 4 – Elastic Decomposition (sketch / detail phases)
# ---------------------------------------------------------------------------


class TicketSketch(BaseModel):
    """Lightweight ticket outline produced in the sketch phase."""

    ticket_key: str = Field(pattern=r"^FORGE-\d+$", examples=["FORGE-1"])
    title: str = Field(min_length=1)
    ticket_type: TicketType
    priority: Priority
    files_owned: list[str] = Field(
        default_factory=list,
        description="File paths this ticket is responsible for creating/modifying",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Ticket keys this ticket depends on",
    )
    user_story_refs: list[str] = Field(
        default_factory=list,
        description="User story IDs this ticket implements",
    )


class PRDBoardSketch(BaseModel):
    """Sketch-phase output: lightweight outline with no descriptions/criteria."""

    board_id: str
    tickets: list[TicketSketch] = Field(min_length=1)
    execution_order: list[list[str]] = Field(min_length=1)
    critical_path: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def execution_order_covers_all_tickets(self) -> Self:
        ticket_keys = {t.ticket_key for t in self.tickets}
        ordered_keys = {key for group in self.execution_order for key in group}
        missing = ticket_keys - ordered_keys
        if missing:
            raise ValueError(f"execution_order is missing tickets: {sorted(missing)}")
        unknown = ordered_keys - ticket_keys
        if unknown:
            raise ValueError(f"execution_order references unknown tickets: {sorted(unknown)}")
        return self


class TicketDetail(BaseModel):
    """Detail-phase output: enrichment for a single ticket."""

    ticket_key: str = Field(pattern=r"^FORGE-\d+$")
    story_points: int = Field(ge=1, le=13)
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Stage 5 – Code Generation
# ---------------------------------------------------------------------------


class TestResults(BaseModel):
    """Aggregate test-run results with pass/fail/skip counts and duration."""

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0, default=0)
    duration_seconds: float = Field(ge=0.0, default=0.0)
    details: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts_add_up(self) -> Self:
        """Validate that passed + failed + skipped equals total."""
        if self.passed + self.failed + self.skipped != self.total:
            raise ValueError(
                f"passed ({self.passed}) + failed ({self.failed}) + skipped ({self.skipped}) "
                f"!= total ({self.total})"
            )
        return self


class CodeArtifact(BaseModel):
    """Stage 5 output: code produced by a developer agent."""

    ticket_key: str = Field(pattern=r"^FORGE-\d+$")
    git_branch: str
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    test_results: TestResults | None = None
    lint_passed: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Stage 6 – QA Review
# ---------------------------------------------------------------------------


class ReviewComment(BaseModel):
    """A code-review comment pinned to a file and optional line number."""

    file_path: str
    line: int | None = None
    severity: str = Field(
        default="info",
        pattern=r"^(info|warning|error|critical)$",
    )
    comment: str


class QAReview(BaseModel):
    """Stage 6 output: QA engineer's review of a code artifact."""

    ticket_key: str = Field(pattern=r"^FORGE-\d+$")
    verdict: QAVerdict
    criteria_compliance: dict[str, bool] = Field(
        description="Acceptance criterion → pass/fail",
    )
    code_quality_score: int = Field(ge=1, le=10)
    comments: list[ReviewComment] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    performance_concerns: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 7 – CTO Intervention
# ---------------------------------------------------------------------------


class PipelineAction(StrEnum):
    """Actions the CTO agent can take on the running pipeline."""

    CONTINUE = "continue"
    PAUSE = "pause"
    RETRY_TICKET = "retry_ticket"
    ABORT = "abort"


class CTODecision(BaseModel):
    """Stage 7 output: CTO intervention decision.

    The CTO prompt allows four intervention types, each with a different set
    of fields.  This model is the union of all fields across all types so
    that ``model_validate_json`` preserves every field the LLM outputs.
    All per-type fields are optional with safe defaults.

    Common fields (all types):
        intervention_type, decision, rationale, pipeline_action

    Conflict resolution:
        action_items, rollback_needed, escalate_to_human,
        ticket_updates, instructions_to_engineer, instructions_to_qa

    Spec ambiguity:
        question, assumptions, impact_assessment, reversibility,
        escalate_to_human

    Pipeline health:
        diagnosis, severity, action, root_cause, prevention

    Human query:
        query, answer, supporting_data, suggested_actions
    """

    # -- Common (all intervention types) ------------------------------------
    intervention_type: str
    decision: str = ""
    rationale: str = ""
    pipeline_action: PipelineAction = PipelineAction.CONTINUE

    # -- Conflict resolution ------------------------------------------------
    action_items: list[dict] = Field(default_factory=list)
    rollback_needed: bool = False
    escalate_to_human: bool = False
    ticket_updates: list[dict] = Field(default_factory=list)
    instructions_to_engineer: str = ""
    instructions_to_qa: str = ""

    # -- Spec ambiguity -----------------------------------------------------
    question: str = ""
    assumptions: list[str] = Field(default_factory=list)
    impact_assessment: str = ""
    reversibility: str = ""

    # -- Pipeline health ----------------------------------------------------
    diagnosis: str = ""
    severity: str = ""
    action: str = ""
    root_cause: str = ""
    prevention: str = ""

    # -- Human query --------------------------------------------------------
    query: str = ""
    answer: str = ""
    supporting_data: dict = Field(default_factory=dict)
    suggested_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline State – accumulates artifacts across all stages
# ---------------------------------------------------------------------------


class PipelineState(BaseModel):
    """Accumulator that carries all artifacts through the pipeline."""

    pipeline_id: UUID = Field(default_factory=uuid4)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    current_stage: str = "initialized"

    # Stage outputs (populated as the pipeline progresses)
    product_spec: ProductSpec | None = None
    enriched_spec: EnrichedSpec | None = None
    tech_spec: TechSpec | None = None
    prd_board: PRDBoard | None = None
    code_artifacts: list[CodeArtifact] = Field(default_factory=list)
    qa_reviews: list[QAReview] = Field(default_factory=list)

    # Metadata
    errors: list[str] = Field(default_factory=list)
    cto_intervention_ids: list[UUID] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Smoke test – validates that schemas can be instantiated end-to-end
# ---------------------------------------------------------------------------


def test_schemas() -> None:
    """Create a minimal valid instance of each major stage model."""

    # -- ProductSpec (Stage 1) --
    spec = ProductSpec(
        spec_id="SPEC-001",
        product_name="Forge",
        product_vision="An AI-driven pipeline that automates the full software delivery lifecycle",
        target_users=["engineering teams"],
        core_problem="Manual ticket grooming and code review is slow and inconsistent",
        proposed_solution="Use LLM agents orchestrated by Temporal to automate spec→code→review",
        user_stories=[
            UserStory(
                id=f"US-{i:03d}",
                persona="developer",
                action=f"action {i}",
                benefit=f"benefit {i}",
                acceptance_criteria=[f"criterion {i}"],
            )
            for i in range(1, 4)
        ],
        success_metrics=["cycle time < 1h", "auto-approval rate > 80%"],
    )
    assert len(spec.user_stories) == 3
    assert spec.product_name == "Forge"

    # -- TechSpec (Stage 3) --
    tech = TechSpec(
        spec_id="TECH-001",
        services=[
            ServiceDefinition(
                name="api-gateway",
                responsibility="HTTP ingress",
                endpoints=[
                    APIEndpoint(method="POST", path="/pipelines", description="Start a run"),
                ],
            ),
        ],
        database_models=[
            DatabaseModel(
                name="PipelineRun",
                table_name="pipeline_runs",
                columns={"id": "UUID PRIMARY KEY", "status": "TEXT NOT NULL"},
            ),
        ],
        api_endpoints=[
            APIEndpoint(method="GET", path="/health"),
        ],
        tech_stack={"language": "Python 3.12", "orchestrator": "Temporal"},
    )
    assert tech.services[0].endpoints[0].method == "POST"

    # -- PRDBoard (Stage 4) --
    tickets = [
        PRDTicket(
            ticket_key=f"FORGE-{i}",
            title=f"Task {i}",
            ticket_type=TicketType.FEATURE,
            priority=Priority.HIGH,
            story_points=3,
            description=f"Implement task {i}",
            acceptance_criteria=[f"criterion {i}"],
            files_owned=[f"src/module_{i}.py"],
        )
        for i in range(1, 4)
    ]
    board = PRDBoard(
        board_id="BOARD-001",
        tickets=tickets,
        execution_order=[["FORGE-1"], ["FORGE-2", "FORGE-3"]],
        critical_path=["FORGE-1", "FORGE-2"],
    )
    assert len(board.tickets) == 3

    # -- QAReview (Stage 6) --
    review = QAReview(
        ticket_key="FORGE-1",
        verdict=QAVerdict.APPROVED,
        criteria_compliance={"criterion 1": True},
        code_quality_score=8,
        comments=[
            ReviewComment(file_path="src/module_1.py", line=42, severity="info", comment="LGTM"),
        ],
    )
    assert review.verdict == QAVerdict.APPROVED
    assert review.code_quality_score == 8

    # -- PipelineState --
    state = PipelineState(
        product_spec=spec,
        tech_spec=tech,
        prd_board=board,
        qa_reviews=[review],
        current_stage="qa_review",
    )
    assert state.product_spec is not None
    assert len(state.qa_reviews) == 1

    print("All schema smoke tests passed.")


if __name__ == "__main__":
    test_schemas()
