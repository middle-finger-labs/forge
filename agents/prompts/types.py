"""Types for the prompt version management subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PromptVersion:
    """A single versioned prompt for an agent stage."""

    id: str = ""
    org_id: str = ""
    stage: int = 0
    agent_role: str = ""
    version: int = 1
    system_prompt: str = ""
    change_summary: str = ""
    is_active: bool = False
    created_by: str = ""
    created_at: datetime | None = None


@dataclass
class PromptEvaluation:
    """Performance record for a prompt version on a single pipeline run."""

    id: str = ""
    org_id: str = ""
    prompt_version_id: str = ""
    pipeline_id: str = ""
    stage: int = 0
    agent_role: str = ""
    verdict: str | None = None
    attempts: int = 1
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    created_at: datetime | None = None


@dataclass
class PromptVersionStats:
    """Aggregated stats for a prompt version."""

    version_id: str = ""
    total_runs: int = 0
    approval_rate: float = 0.0
    avg_cost_usd: float = 0.0
    avg_duration_seconds: float = 0.0
    avg_attempts: float = 0.0
    error_count: int = 0
