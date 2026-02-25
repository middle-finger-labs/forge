"""High-level convenience functions for common agent communication patterns.

These wrap ``AgentBus.ask()`` to produce formatted context blocks that get
injected into agent prompts at the orchestration layer.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.communication.agent_bus import AgentBus
from contracts.schemas import AgentRole

log = structlog.get_logger().bind(component="agent_briefing")

# Rough token-to-char ratio for truncation (~4 chars per token)
_MAX_RESPONSE_CHARS = 4000  # ~1000 tokens


async def get_architect_briefing(
    bus: AgentBus,
    ticket: dict[str, Any],
    tech_spec_context: str | dict = "",
) -> str:
    """Ask the Architect for guidance before a coding agent starts.

    Returns a formatted ``<architect_briefing>`` block, or ``""`` on failure.
    """
    title = ticket.get("title", ticket.get("ticket_key", "unknown ticket"))
    files_owned = ticket.get("files_owned", [])
    acceptance = ticket.get("acceptance_criteria", [])

    question = (
        f"I'm about to implement ticket '{title}'. "
        f"Files I own: {json.dumps(files_owned)}. "
        f"Acceptance criteria: {json.dumps(acceptance)}. "
        "What architecture patterns should I follow, what dependency "
        "interfaces should I code against, and are there any gotchas "
        "I should watch out for?"
    )

    context_str = (
        json.dumps(tech_spec_context)[:2000]
        if isinstance(tech_spec_context, dict)
        else str(tech_spec_context)[:2000]
    )

    response = await bus.ask(
        AgentRole.DEVELOPER,
        AgentRole.ARCHITECT,
        question,
        context=context_str,
    )

    if response.hit_limit or response.timed_out or not response.response:
        return ""

    text = response.response[:_MAX_RESPONSE_CHARS]
    return f"<architect_briefing>\n{text}\n</architect_briefing>"


async def get_qa_clarification(
    bus: AgentBus,
    ticket: dict[str, Any],
    qa_review: dict[str, Any],
    code_artifact: dict[str, Any],
) -> str:
    """Ask the Engineer to explain their implementation decisions.

    Used by QA when revision_instructions exist, so the engineer can
    clarify whether behavior is intentional vs. a bug.

    Returns a formatted ``<engineer_clarification>`` block, or ``""``.
    """
    revision_instructions = qa_review.get("revision_instructions", [])
    comments = qa_review.get("comments", [])

    if not revision_instructions and not comments:
        return ""

    issues_summary = "; ".join(revision_instructions[:3])
    if comments:
        comment_texts = [
            c.get("comment", "")
            for c in comments[:3]
            if c.get("severity") in ("error", "critical")
        ]
        if comment_texts:
            issues_summary += " | Comments: " + "; ".join(comment_texts)

    ticket_key = ticket.get("ticket_key", "unknown")
    question = (
        f"QA found issues with your implementation of {ticket_key}: "
        f"{issues_summary}. "
        "Can you explain your implementation approach and whether these "
        "behaviors are intentional design decisions or bugs?"
    )

    context = json.dumps({
        "ticket_key": ticket_key,
        "files_created": code_artifact.get("files_created", []),
        "files_modified": code_artifact.get("files_modified", []),
        "notes": code_artifact.get("notes", ""),
    })[:2000]

    response = await bus.ask(
        AgentRole.QA_ENGINEER,
        AgentRole.DEVELOPER,
        question,
        context=context,
    )

    if response.hit_limit or response.timed_out or not response.response:
        return ""

    text = response.response[:_MAX_RESPONSE_CHARS]
    return f"<engineer_clarification>\n{text}\n</engineer_clarification>"


async def ask_any_agent(
    bus: AgentBus,
    from_role: str,
    to_role: str,
    question: str,
    context: str = "",
) -> str:
    """Generic helper for any agent to ask any other agent.

    Returns a formatted ``<agent_response>`` block, or ``""``.
    """
    response = await bus.ask(from_role, to_role, question, context=context)

    if response.hit_limit or response.timed_out or not response.response:
        return ""

    text = response.response[:_MAX_RESPONSE_CHARS]
    return f'<agent_response from="{to_role}">\n{text}\n</agent_response>'
