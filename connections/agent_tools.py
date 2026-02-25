"""Bridge between MCP connections and agent execution.

Assembles the permission-filtered MCP tools available to a specific agent,
wraps them in ``AgentTool`` descriptors that carry routing metadata, and
provides ``execute_tool()`` to dispatch calls through the MCP client manager.

Usage::

    from connections.agent_tools import AgentConnectionTools

    act = AgentConnectionTools(client_manager, tool_filter)

    # Before an agent runs — gather its tools
    tools = await act.get_tools_for_agent(org_id, "business_analyst")

    # When the LLM invokes a tool
    result = await act.execute_tool(
        tool,
        arguments={"query": "roadmap"},
        org_id="org-123",
        agent_role="business_analyst",
        pipeline_id="pipe-456",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from connections.client_manager import MCPClientManager
from connections.tool_filter import ToolFilter

log = structlog.get_logger().bind(component="connections.agent_tools")

# Service display icons for pipeline conversation logging
_SERVICE_ICONS: dict[str, str] = {
    "notion": "\U0001f4d3",      # notebook
    "linear": "\U0001f537",      # diamond
    "figma": "\U0001f3a8",       # palette
    "jira": "\U0001f3ab",        # ticket
    "google_drive": "\U0001f4c4",  # page
}

# Agent role display labels for log messages
_AGENT_LABELS: dict[str, str] = {
    "business_analyst": "BA",
    "ba": "BA",
    "researcher": "Researcher",
    "architect": "Architect",
    "pm": "PM",
    "engineer": "Engineer",
    "qa": "QA",
    "cto": "CTO",
}


@dataclass
class AgentTool:
    """An MCP tool wrapped with routing metadata for agent execution.

    The ``name`` is namespace-prefixed (e.g. ``notion_search``) so the
    LLM sees a globally unique identifier.  ``original_tool_name`` is
    the name the MCP server expects.
    """

    name: str                      # namespaced: {service}_{tool_name}
    description: str               # [Display Name] original description
    input_schema: dict             # JSON Schema for the tool's parameters
    connection_id: str             # routes call to the right MCP session
    original_tool_name: str        # tool name on the MCP server
    service: str = ""              # service type value (e.g. "notion")
    display_name: str = ""         # human label for the connection


class AgentConnectionTools:
    """Assembles and dispatches MCP tools for a specific agent."""

    def __init__(
        self,
        client_manager: MCPClientManager,
        tool_filter: ToolFilter | None = None,
    ) -> None:
        self.client_manager = client_manager
        self.tool_filter = tool_filter or ToolFilter()

    # ── Gather tools ───────────────────────────────────────

    async def get_tools_for_agent(
        self,
        org_id: str,
        agent_role: str,
    ) -> list[AgentTool]:
        """Return all MCP tools available to *agent_role* across all connections.

        For each enabled connection:
        1. List tools from the MCP server (uses cached session if available)
        2. Apply permission filters
        3. Wrap in ``AgentTool`` with routing metadata
        """
        connections = await self.client_manager.registry.list_connections(org_id)
        all_tools: list[AgentTool] = []

        for conn in connections:
            if not conn.enabled:
                continue

            try:
                raw_tools = await self.client_manager.list_tools(conn.id)
            except Exception as exc:
                log.warning(
                    "failed to list tools for connection",
                    connection_id=conn.id,
                    service=conn.service.value,
                    error=str(exc),
                )
                continue

            allowed_tools = self.tool_filter.filter_tools_for_agent(
                raw_tools, conn, agent_role
            )

            for tool in allowed_tools:
                tool_name = tool.get("name", "")
                all_tools.append(
                    AgentTool(
                        name=f"{conn.service.value}_{tool_name}",
                        description=f"[{conn.display_name}] {tool.get('description', '')}",
                        input_schema=tool.get("input_schema", {}),
                        connection_id=conn.id,
                        original_tool_name=tool_name,
                        service=conn.service.value,
                        display_name=conn.display_name,
                    )
                )

        log.info(
            "assembled agent tools",
            agent_role=agent_role,
            org_id=org_id,
            tool_count=len(all_tools),
            connections=len(connections),
        )
        return all_tools

    # ── Execute tool ───────────────────────────────────────

    async def execute_tool(
        self,
        agent_tool: AgentTool,
        arguments: dict,
        *,
        org_id: str | None = None,
        agent_role: str | None = None,
        pipeline_id: str | None = None,
    ) -> dict:
        """Execute an MCP tool call through the client manager.

        Returns ``{"content": [...], "is_error": bool}``.

        Also streams a human-readable log entry to the pipeline conversation
        so the dashboard shows what the agent did.
        """
        result = await self.client_manager.call_tool(
            agent_tool.connection_id,
            agent_tool.original_tool_name,
            arguments,
            org_id=org_id,
            agent_role=agent_role,
            pipeline_id=pipeline_id,
        )

        # Stream to pipeline conversation
        if pipeline_id:
            await self._log_to_pipeline(
                pipeline_id=pipeline_id,
                agent_role=agent_role,
                agent_tool=agent_tool,
                arguments=arguments,
                result=result,
            )

        return result

    # ── Convert to LLM tool definitions ────────────────────

    @staticmethod
    def to_llm_tool_definitions(tools: list[AgentTool]) -> list[dict]:
        """Convert AgentTool list to Anthropic/OpenAI function-calling format.

        Returns a list of tool dicts ready to pass to the LLM's ``tools``
        parameter (compatible with both Anthropic and OpenAI formats).
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    @staticmethod
    def find_tool_by_name(
        tools: list[AgentTool],
        name: str,
    ) -> AgentTool | None:
        """Look up an AgentTool by its namespaced name."""
        for tool in tools:
            if tool.name == name:
                return tool
        return None

    # ── Internal: pipeline conversation logging ────────────

    async def _log_to_pipeline(
        self,
        *,
        pipeline_id: str,
        agent_role: str | None,
        agent_tool: AgentTool,
        arguments: dict,
        result: dict,
    ) -> None:
        """Stream a tool-call event to the pipeline log for dashboard display.

        Format examples:
            "BA used Notion: Searched for 'product requirements' -> found 3 pages"
            "PM used Linear: Created issue LIN-42 'Implement health check'"
        """
        try:
            from memory.agent_log import stream_agent_log

            icon = _SERVICE_ICONS.get(agent_tool.service, "\U0001f527")  # wrench fallback
            summary = _build_tool_summary(agent_tool, arguments, result, agent_role)

            await stream_agent_log(
                pipeline_id,
                "mcp.tool_call",
                agent_role=agent_role,
                payload={
                    "icon": icon,
                    "service": agent_tool.service,
                    "display_name": agent_tool.display_name,
                    "tool_name": agent_tool.original_tool_name,
                    "namespaced_name": agent_tool.name,
                    "arguments_preview": _truncate_args(arguments),
                    "summary": summary,
                    "is_error": result.get("is_error", False),
                },
            )
        except Exception as exc:
            log.debug("pipeline tool log failed", error=str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_tool_summary(
    tool: AgentTool,
    arguments: dict,
    result: dict,
    agent_role: str | None = None,
) -> str:
    """Build a one-line human-readable summary of the tool call.

    Format examples:
        "📓 BA searched Notion for 'authentication flow' → found 2 pages"
        "🔷 PM created Linear issue LIN-42: 'Implement health check endpoint'"
        "🎨 Engineer read Figma design 'Login Screen v3' for component specs"
    """
    icon = _SERVICE_ICONS.get(tool.service, "\U0001f527")
    role_label = _AGENT_LABELS.get(agent_role or "", tool.service.replace("_", " ").title())
    service_name = tool.display_name or tool.service.replace("_", " ").title()

    # Determine action verb from tool name
    tool_lower = tool.original_tool_name.lower()
    action = _infer_action_verb(tool_lower)

    # Extract the most relevant argument for the summary
    subject = ""
    for key in ("query", "title", "name", "text", "search", "page_id", "issue_id", "url"):
        if key in arguments:
            val = str(arguments[key])
            subject = f"'{val[:60]}'" if len(val) > 60 else f"'{val}'"
            break
    if not subject and arguments:
        first_key = next(iter(arguments))
        val = str(arguments[first_key])
        subject = f"'{val[:50]}'" if len(val) > 50 else f"'{val}'"

    # Extract result info
    is_error = result.get("is_error", False)
    content_blocks = result.get("content", [])

    if is_error:
        error_text = content_blocks[0].get("text", "unknown error") if content_blocks else "unknown error"
        return f"{icon} {role_label} {action} {service_name} {subject} \u2014 failed: {error_text[:80]}"

    # Extract result hint (count, ID, summary)
    result_hint = _extract_result_hint(content_blocks)

    parts = [f"{icon} {role_label} {action} {service_name}"]
    if subject:
        parts.append(f"for {subject}" if action in ("searched", "queried", "fetched") else subject)
    if result_hint:
        parts.append(f"\u2192 {result_hint}")

    return " ".join(parts)


def _infer_action_verb(tool_name: str) -> str:
    """Infer a past-tense action verb from the tool name."""
    if any(w in tool_name for w in ("search", "query", "find", "list")):
        return "searched"
    if any(w in tool_name for w in ("get", "read", "fetch", "retrieve")):
        return "read"
    if any(w in tool_name for w in ("create", "add", "post")):
        return "created"
    if any(w in tool_name for w in ("update", "edit", "modify", "put", "set")):
        return "updated"
    if any(w in tool_name for w in ("delete", "remove", "archive")):
        return "deleted"
    return "used"


def _extract_result_hint(content_blocks: list) -> str:
    """Extract a short result hint from MCP response content blocks."""
    if not content_blocks:
        return ""
    first_text = content_blocks[0].get("text", "")
    if not first_text:
        return ""
    # Try to detect common patterns: counts, IDs, titles
    text = first_text.strip()
    if len(text) <= 100:
        return text
    # Truncate long results
    return text[:100] + "\u2026"


def _truncate_args(arguments: dict, max_len: int = 200) -> dict:
    """Truncate long argument values for logging (not for MCP call)."""
    truncated: dict = {}
    for k, v in arguments.items():
        s = str(v)
        truncated[k] = s[:max_len] + "..." if len(s) > max_len else v
    return truncated
