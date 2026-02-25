"""Types for agent-to-agent communication."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentResponse:
    """Result of an inter-agent question via the AgentBus."""

    from_role: str
    to_role: str
    question: str
    response: str
    cost_usd: float = 0.0
    timed_out: bool = False
    hit_limit: bool = False
    circular: bool = False
