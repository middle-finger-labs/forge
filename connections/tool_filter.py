"""Permission-based MCP tool filtering.

Classifies each MCP tool as read/write/admin based on its name and
description, then filters the tool list for a specific agent based on
the connection's permission hierarchy:

    1. Connection-level ``default_permission``
    2. Agent-level overrides (``agent_permissions``)
    3. Tool-level overrides (``tool_permissions``)

Usage::

    from connections.tool_filter import ToolFilter

    tf = ToolFilter()
    allowed = tf.filter_tools_for_agent(raw_tools, connection, "business_analyst")
"""

from __future__ import annotations

from connections.models import ConnectionConfig, PermissionLevel, ToolPermission


class ToolFilter:
    """Filters MCP tools based on permissions before an agent can use them."""

    READ_PATTERNS = ["list", "get", "search", "fetch", "read", "query", "find"]
    WRITE_PATTERNS = [
        "create", "update", "add", "set", "post", "put",
        "edit", "modify", "write", "send", "submit",
    ]
    ADMIN_PATTERNS = ["delete", "remove", "archive", "destroy", "drop", "purge"]

    # ── Classification ─────────────────────────────────────

    def classify_tool(self, tool_name: str, tool_description: str = "") -> str:
        """Classify a tool as ``'read'``, ``'write'``, or ``'admin'``.

        Checks name first (stronger signal), then description as fallback.
        Admin patterns take precedence over write patterns.
        """
        name_lower = tool_name.lower()
        desc_lower = (tool_description or "").lower()

        # Admin check first (most restrictive)
        if any(p in name_lower for p in self.ADMIN_PATTERNS):
            return "admin"
        if any(p in desc_lower for p in self.ADMIN_PATTERNS):
            return "admin"

        # Write check
        if any(p in name_lower for p in self.WRITE_PATTERNS):
            return "write"
        if any(p in desc_lower for p in self.WRITE_PATTERNS):
            return "write"

        # Default to read
        return "read"

    # ── Filtering ──────────────────────────────────────────

    def filter_tools_for_agent(
        self,
        tools: list[dict],
        connection: ConnectionConfig,
        agent_role: str,
    ) -> list[dict]:
        """Return only the tools this agent is allowed to use.

        Permission hierarchy:
        - ``NONE``:  no tools
        - ``READ``:  read-classified tools only
        - ``WRITE``: read + write tools (no admin)
        - ``FULL``:  everything

        Tool-level overrides (``connection.tool_permissions``) can further
        restrict or scope tools to specific agents.
        """
        agent_perm = connection.get_agent_permission(agent_role)

        if agent_perm == PermissionLevel.NONE:
            return []

        # Build a quick lookup for tool-level overrides
        tool_overrides: dict[str, ToolPermission] = {
            tp.tool_name: tp for tp in connection.tool_permissions
        }

        filtered: list[dict] = []
        for tool in tools:
            tool_name = tool.get("name", "")
            tool_desc = tool.get("description", "")

            # 1. Tool-level override check
            override = tool_overrides.get(tool_name)
            if override is not None:
                if not override.allowed:
                    continue
                if (
                    override.allowed_agents is not None
                    and agent_role not in override.allowed_agents
                ):
                    continue

            # 2. Permission-level check
            tool_class = self.classify_tool(tool_name, tool_desc)

            if agent_perm == PermissionLevel.READ and tool_class != "read":
                continue
            if agent_perm == PermissionLevel.WRITE and tool_class == "admin":
                continue
            # FULL gets everything

            filtered.append(tool)

        return filtered
