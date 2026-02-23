"""Operational configuration for every agent in the Forge pipeline.

Defines model tiers, per-agent settings, retry policies, pipeline-level
limits, and cost estimation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.schemas import AgentRole

# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Which model an agent calls and how."""

    primary_model: str
    fallback_model: str | None = None
    max_tokens: int = 8192
    temperature: float = 0.1
    timeout_seconds: int = 120


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry behaviour for transient failures."""

    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    retry_on: tuple[str, ...] = (
        "rate_limit_error",
        "api_connection_error",
        "overloaded_error",
        "timeout",
    )
    do_not_retry_on: tuple[str, ...] = (
        "authentication_error",
        "invalid_request_error",
        "permission_error",
    )


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Complete operational config for a single agent."""

    role: AgentRole
    display_name: str
    model: ModelConfig
    retry: RetryConfig = field(default_factory=RetryConfig)
    allowed_tools: tuple[str, ...] = ()
    max_iterations: int = 10
    output_schema: str = ""
    human_approval_required: bool = False
    cost_budget_usd: float | None = None


# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------

SONNET_4_5 = "claude-sonnet-4-5-20250929"
HAIKU_4_5 = "claude-haiku-4-5-20241022"
LOCAL_QWEN = "litellm/ollama/qwen2.5-coder:32b"

FRONTIER = ModelConfig(
    primary_model=SONNET_4_5,
    fallback_model=None,
    max_tokens=16384,
    temperature=0.1,
    timeout_seconds=180,
)

STRONG = ModelConfig(
    primary_model=SONNET_4_5,
    fallback_model=HAIKU_4_5,
    max_tokens=8192,
    temperature=0.1,
    timeout_seconds=120,
)

LOCAL_CODER = ModelConfig(
    primary_model=LOCAL_QWEN,
    fallback_model=SONNET_4_5,
    max_tokens=8192,
    temperature=0.1,
    timeout_seconds=300,
)


# ---------------------------------------------------------------------------
# Per-agent configurations
# ---------------------------------------------------------------------------

AGENT_CONFIGS: dict[AgentRole, AgentConfig] = {
    AgentRole.PRODUCT_MANAGER: AgentConfig(
        role=AgentRole.PRODUCT_MANAGER,
        display_name="Business Analyst",
        model=STRONG,
        allowed_tools=(),
        max_iterations=10,
        output_schema="ProductSpec",
        human_approval_required=True,
        cost_budget_usd=2.0,
    ),
    AgentRole.RESEARCH_ANALYST: AgentConfig(
        role=AgentRole.RESEARCH_ANALYST,
        display_name="Product Researcher",
        model=STRONG,
        allowed_tools=("web_search", "web_fetch"),
        max_iterations=15,
        output_schema="EnrichedSpec",
        human_approval_required=False,
        cost_budget_usd=5.0,
    ),
    AgentRole.ARCHITECT: AgentConfig(
        role=AgentRole.ARCHITECT,
        display_name="Technical Architect",
        model=FRONTIER,
        allowed_tools=(),
        max_iterations=10,
        output_schema="TechSpec",
        human_approval_required=True,
        cost_budget_usd=3.0,
    ),
    AgentRole.TICKET_MANAGER: AgentConfig(
        role=AgentRole.TICKET_MANAGER,
        display_name="Project Manager",
        model=STRONG,
        allowed_tools=(),
        max_iterations=10,
        output_schema="PRDBoard",
        human_approval_required=False,
        cost_budget_usd=2.0,
    ),
    AgentRole.DEVELOPER: AgentConfig(
        role=AgentRole.DEVELOPER,
        display_name="Software Engineer",
        model=LOCAL_CODER,
        allowed_tools=("bash", "read_file", "write_file", "edit_file"),
        max_iterations=30,
        output_schema="CodeArtifact",
        human_approval_required=False,
        cost_budget_usd=10.0,
    ),
    AgentRole.QA_ENGINEER: AgentConfig(
        role=AgentRole.QA_ENGINEER,
        display_name="QA Engineer",
        model=FRONTIER,
        allowed_tools=("read_file", "bash"),
        max_iterations=10,
        output_schema="QAReview",
        human_approval_required=False,
        cost_budget_usd=3.0,
    ),
    AgentRole.CTO: AgentConfig(
        role=AgentRole.CTO,
        display_name="CTO",
        model=FRONTIER,
        allowed_tools=("read_file", "web_search"),
        max_iterations=10,
        output_schema="",
        human_approval_required=False,
        cost_budget_usd=5.0,
    ),
}


# ---------------------------------------------------------------------------
# Pipeline-level configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostLimits:
    """Kill-switch thresholds for pipeline spend."""

    alert_usd: float = 25.0
    kill_switch_usd: float = 50.0


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Top-level settings governing a full pipeline run."""

    max_concurrent_engineers: int = 4
    max_qa_cycles: int = 3
    auto_merge: bool = False
    auto_approve_minor_only: bool = False

    # Per-stage timeouts (seconds)
    stage_timeouts: dict[str, int] = field(
        default_factory=lambda: {
            "product_spec": 300,
            "research": 600,
            "architecture": 300,
            "tickets": 300,
            "engineering": 900,
            "qa_review": 300,
            "cto_intervention": 180,
        }
    )

    cost_limits: CostLimits = field(default_factory=CostLimits)

    # Stages that block until a human approves the artifact
    human_approval_stages: tuple[str, ...] = ("product_spec", "architecture")

    # Event types broadcast to subscribers (Redis pub/sub, WebSocket, etc.)
    broadcast_events: tuple[str, ...] = (
        "pipeline.started",
        "pipeline.completed",
        "pipeline.failed",
        "stage.started",
        "stage.completed",
        "stage.failed",
        "ticket.assigned",
        "ticket.completed",
        "qa.verdict",
        "cto.intervention",
        "cost.alert",
        "cost.kill_switch",
        "human.approval_required",
        "human.approval_received",
    )


# Singleton — import and use directly
PIPELINE_CONFIG = PipelineConfig()


# ---------------------------------------------------------------------------
# Pricing data (USD per million tokens, Anthropic API direct)
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    # model_id: (input_per_mtok, output_per_mtok)
    SONNET_4_5: (3.00, 15.00),
    HAIKU_4_5: (1.00, 5.00),
    LOCAL_QWEN: (0.00, 0.00),
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_agent_config(role: AgentRole) -> AgentConfig:
    """Return the AgentConfig for a given role.

    Raises KeyError with a clear message if the role is not configured.
    """
    try:
        return AGENT_CONFIGS[role]
    except KeyError:
        configured = ", ".join(r.value for r in AGENT_CONFIGS)
        raise KeyError(
            f"No agent config for role {role!r}. Configured roles: {configured}"
        ) from None


Complexity = Literal["low", "medium", "high"]


def get_model_for_task(complexity: Complexity) -> ModelConfig:
    """Pick the cheapest model tier that can handle the task complexity.

    - low    → LOCAL_CODER  (free local inference, sonnet fallback)
    - medium → STRONG       (sonnet primary, haiku fallback)
    - high   → FRONTIER     (sonnet primary, no fallback, 16k output)
    """
    return {
        "low": LOCAL_CODER,
        "medium": STRONG,
        "high": FRONTIER,
    }[complexity]


_anthropic_client: object | None = None


def get_anthropic_client():
    """Process-wide shared Anthropic client with connection pooling."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        import httpx

        _anthropic_client = anthropic.AsyncAnthropic(
            http_client=httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                ),
                timeout=httpx.Timeout(timeout=180.0),
            ),
        )
    return _anthropic_client


def estimate_cost(
    role: AgentRole,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate the USD cost for a single agent invocation.

    Uses the agent's *primary* model pricing. Returns 0.0 for local models.
    Actual cost may differ if the fallback model is used.
    """
    config = get_agent_config(role)
    model_id = config.model.primary_model
    input_rate, output_rate = _PRICING.get(model_id, (0.0, 0.0))
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
