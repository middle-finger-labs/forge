"""Tests for MCP connection pipeline integration.

Covers:
    - Pipeline hooks (on_start, on_stage_complete, on_complete, on_failure)
    - Agent tool injection and filtering
    - Tool call logging to pipeline conversation
    - Tool call audit log completeness
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connections.models import (
    ConnectionConfig,
    PermissionLevel,
    ServiceType,
    ToolPermission,
    TransportType,
)
from connections.pipeline_hooks import (
    ConnectionPipelineHooks,
    DEFAULT_AUTOMATION,
    get_pipeline_hooks,
)
from connections.tool_filter import ToolFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


def _make_config(
    service: ServiceType = ServiceType.NOTION,
    default_permission: PermissionLevel = PermissionLevel.WRITE,
    automation_config: dict | None = None,
    tool_permissions: list | None = None,
    discovered_tools: list | None = None,
    enabled: bool = True,
) -> ConnectionConfig:
    return ConnectionConfig(
        id=_uid(),
        org_id="org-test",
        service=service,
        display_name=f"Test {service.value.title()}",
        transport=TransportType.STREAMABLE_HTTP,
        server_url="https://mcp.example.com",
        default_permission=default_permission,
        tool_permissions=tool_permissions or [],
        discovered_tools=discovered_tools or [],
        enabled=enabled,
        automation_config=automation_config or {},
    )


@pytest.fixture
def hooks():
    """Create a fresh hooks instance with mocked internals."""
    h = ConnectionPipelineHooks()
    # Mock the registry to return test connections
    h._registry = AsyncMock()
    # Mock the client manager to capture tool calls
    h._manager = AsyncMock()
    return h


# ---------------------------------------------------------------------------
# Pipeline hooks — on_pipeline_start
# ---------------------------------------------------------------------------


class TestOnPipelineStart:
    async def test_searches_notion_for_related_docs(self, hooks):
        notion_conn = _make_config(
            service=ServiceType.NOTION,
            automation_config={"auto_search_context": True},
        )
        hooks._registry.list_connections = AsyncMock(return_value=[notion_conn])

        hooks._manager.call_tool = AsyncMock(
            return_value={
                "content": [{"text": "Found: Auth Architecture doc"}],
                "is_error": False,
            }
        )

        context = await hooks.on_pipeline_start(
            "pipe-1", "org-test", "Add user preferences API"
        )

        assert len(context["notion_pages"]) == 1
        assert "Auth Architecture" in context["notion_pages"][0]["content"]

    async def test_searches_linear_for_related_tickets(self, hooks):
        linear_conn = _make_config(
            service=ServiceType.LINEAR,
            automation_config={"auto_search_context": True},
        )
        hooks._registry.list_connections = AsyncMock(
            side_effect=lambda org_id: [
                c for c in [linear_conn] if c.service.value in ("linear",)
            ]
        )

        # Make _get_connections return appropriate connections per service
        async def _get_conns(org_id, service=None):
            if service == "linear":
                return [linear_conn]
            return []

        hooks._get_connections = _get_conns

        hooks._manager.call_tool = AsyncMock(
            return_value={
                "content": [{"text": "PREF-123: User preferences endpoint"}],
                "is_error": False,
            }
        )

        context = await hooks.on_pipeline_start(
            "pipe-1", "org-test", "Add user preferences API"
        )

        assert len(context["related_tickets"]) == 1

    async def test_skips_search_when_automation_disabled(self, hooks):
        notion_conn = _make_config(
            service=ServiceType.NOTION,
            automation_config={"auto_search_context": False},
        )

        async def _get_conns(org_id, service=None):
            if service == "notion":
                return [notion_conn]
            return []

        hooks._get_connections = _get_conns

        context = await hooks.on_pipeline_start(
            "pipe-1", "org-test", "Some spec"
        )
        # Should not have called any tools
        hooks._manager.call_tool.assert_not_called()
        assert context["notion_pages"] == []

    async def test_handles_search_failure_gracefully(self, hooks):
        notion_conn = _make_config(service=ServiceType.NOTION)

        async def _get_conns(org_id, service=None):
            if service == "notion":
                return [notion_conn]
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(side_effect=Exception("MCP down"))

        # Should not raise
        context = await hooks.on_pipeline_start(
            "pipe-1", "org-test", "Some spec"
        )
        assert context["notion_pages"] == []


# ---------------------------------------------------------------------------
# Pipeline hooks — on_stage_complete
# ---------------------------------------------------------------------------


class TestOnStageComplete:
    async def test_ba_complete_creates_notion_page(self, hooks):
        notion_conn = _make_config(
            service=ServiceType.NOTION,
            automation_config={"auto_create_spec_page": True},
        )

        async def _get_conns(org_id, service=None):
            if service == "notion":
                return [notion_conn]
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(
            return_value={"content": [{"text": "Page created"}], "is_error": False}
        )

        ba_output = {
            "product_name": "User Preferences",
            "product_vision": "Let users customize their experience",
            "user_stories": [
                {"id": "US-001", "action": "Set theme preference"},
            ],
        }

        await hooks.on_stage_complete(
                "pipe-1", "org-test", "business_analysis", ba_output
            )

        # Should have called create_page
        hooks._manager.call_tool.assert_called_once()
        call_args = hooks._manager.call_tool.call_args
        assert call_args[0][1] == "create_page"  # tool_name
        assert "User Preferences" in call_args[0][2]["title"]

    async def test_pm_complete_creates_linear_tickets(self, hooks):
        linear_conn = _make_config(
            service=ServiceType.LINEAR,
            automation_config={"auto_create_tickets": True},
        )

        async def _get_conns(org_id, service=None):
            if service in ("linear", "jira"):
                return [linear_conn] if service == "linear" else []
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(
            return_value={"content": [{"text": "Issue created"}], "is_error": False}
        )

        pm_output = {
            "tickets": [
                {
                    "ticket_key": "FORGE-1",
                    "title": "Set up database schema",
                    "description": "Create preferences table",
                    "priority": "high",
                },
                {
                    "ticket_key": "FORGE-2",
                    "title": "Add API endpoints",
                    "description": "CRUD for preferences",
                    "priority": "medium",
                },
            ],
        }

        await hooks.on_stage_complete(
                "pipe-1", "org-test", "pm", pm_output
            )

        # Should have called create_issue twice
        assert hooks._manager.call_tool.call_count == 2

    async def test_qa_complete_creates_bug_tickets(self, hooks):
        linear_conn = _make_config(
            service=ServiceType.LINEAR,
            automation_config={"auto_create_bug_tickets": True},
        )

        async def _get_conns(org_id, service=None):
            if service in ("linear", "jira"):
                return [linear_conn] if service == "linear" else []
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(
            return_value={"content": [{"text": "Bug created"}], "is_error": False}
        )

        qa_output = {
            "ticket_key": "FORGE-1",
            "verdict": "needs_revision",
            "comments": [
                {
                    "file_path": "src/service.ts",
                    "line": 42,
                    "severity": "critical",
                    "comment": "SQL injection via string concatenation",
                },
                {
                    "file_path": "src/service.ts",
                    "line": 10,
                    "severity": "info",
                    "comment": "Good error handling",
                },
            ],
        }

        await hooks.on_stage_complete(
                "pipe-1", "org-test", "qa_review", qa_output
            )

        # Should have created only 1 bug ticket (for the critical finding)
        assert hooks._manager.call_tool.call_count == 1
        call_args = hooks._manager.call_tool.call_args
        assert "SQL injection" in call_args[0][2]["title"]

    async def test_qa_approved_creates_no_tickets(self, hooks):
        linear_conn = _make_config(service=ServiceType.LINEAR)

        async def _get_conns(org_id, service=None):
            if service in ("linear", "jira"):
                return [linear_conn] if service == "linear" else []
            return []

        hooks._get_connections = _get_conns

        qa_output = {"verdict": "approved", "comments": []}

        await hooks.on_stage_complete(
            "pipe-1", "org-test", "qa_review", qa_output
        )
        hooks._manager.call_tool.assert_not_called()

    async def test_unknown_stage_does_nothing(self, hooks):
        await hooks.on_stage_complete(
            "pipe-1", "org-test", "some_unknown_stage", {}
        )
        hooks._manager.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Pipeline hooks — on_pipeline_complete
# ---------------------------------------------------------------------------


class TestOnPipelineComplete:
    async def test_updates_tickets_to_done(self, hooks):
        linear_conn = _make_config(
            service=ServiceType.LINEAR,
            automation_config={"auto_update_tickets": True},
        )

        async def _get_conns(org_id, service=None):
            if service in ("linear", "jira"):
                return [linear_conn] if service == "linear" else []
            if service == "notion":
                return []
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(
            return_value={"content": [{"text": "Updated"}], "is_error": False}
        )

        result = {
            "name": "User Preferences",
            "completed_tickets": ["FORGE-1", "FORGE-2", "FORGE-3"],
            "total_cost_usd": 1.50,
        }

        await hooks.on_pipeline_complete("pipe-1", "org-test", result)

        # 3 tickets should have been updated
        update_calls = [
            c for c in hooks._manager.call_tool.call_args_list
            if c[0][1] == "update_issue"
        ]
        assert len(update_calls) == 3

    async def test_creates_completion_notion_page(self, hooks):
        notion_conn = _make_config(
            service=ServiceType.NOTION,
            automation_config={"auto_create_spec_page": True},
        )

        async def _get_conns(org_id, service=None):
            if service == "notion":
                return [notion_conn]
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(
            return_value={"content": [{"text": "Page created"}], "is_error": False}
        )

        result = {
            "name": "User Preferences",
            "completed_tickets": [],
            "total_cost_usd": 1.50,
        }

        await hooks.on_pipeline_complete("pipe-1", "org-test", result)

        hooks._manager.call_tool.assert_called_once()
        call_args = hooks._manager.call_tool.call_args
        assert "Pipeline Complete" in call_args[0][2]["title"]


# ---------------------------------------------------------------------------
# Pipeline hooks — on_pipeline_failure
# ---------------------------------------------------------------------------


class TestOnPipelineFailure:
    async def test_creates_failure_ticket(self, hooks):
        linear_conn = _make_config(
            service=ServiceType.LINEAR,
            automation_config={"auto_create_bug_tickets": True},
        )

        async def _get_conns(org_id, service=None):
            if service in ("linear", "jira"):
                return [linear_conn] if service == "linear" else []
            if service == "notion":
                return []
            return []

        hooks._get_connections = _get_conns
        hooks._manager.call_tool = AsyncMock(
            return_value={"content": [{"text": "Created"}], "is_error": False}
        )

        error = {
            "message": "Architect agent timed out after 120s",
            "stage": "architecture",
        }

        await hooks.on_pipeline_failure("pipe-1", "org-test", error)

        # Should create failure ticket + Notion page
        assert hooks._manager.call_tool.call_count >= 1
        create_calls = [
            c for c in hooks._manager.call_tool.call_args_list
            if c[0][1] == "create_issue"
        ]
        assert len(create_calls) >= 1
        assert "Pipeline Failed" in create_calls[0][0][2]["title"]


# ---------------------------------------------------------------------------
# Automation flag tests
# ---------------------------------------------------------------------------


class TestAutomationFlags:
    def test_default_automation_all_on(self):
        for key, value in DEFAULT_AUTOMATION.items():
            assert value is True, f"{key} should default to True"

    def test_get_automation_uses_connection_config(self, hooks):
        conn = _make_config(
            automation_config={"auto_create_tickets": False}
        )
        assert hooks._get_automation(conn, "auto_create_tickets") is False
        # Unset flags should fall back to defaults
        assert hooks._get_automation(conn, "auto_search_context") is True

    def test_get_automation_missing_config(self, hooks):
        """Connection with no automation_config should use defaults."""
        conn = _make_config(automation_config={})
        assert hooks._get_automation(conn, "auto_create_tickets") is True


# ---------------------------------------------------------------------------
# Agent tool injection tests
# ---------------------------------------------------------------------------


class TestAgentToolInjection:
    """Test that agents receive correctly filtered tools."""

    async def test_read_only_agent_gets_read_tools(self):
        config = _make_config(
            default_permission=PermissionLevel.READ,
            discovered_tools=[
                {"name": "search", "description": "Search pages"},
                {"name": "create_page", "description": "Create page"},
                {"name": "delete_page", "description": "Delete page"},
            ],
        )
        tool_filter = ToolFilter()

        tools = tool_filter.filter_tools_for_agent(
            config.discovered_tools, config, "researcher"
        )
        names = [t["name"] for t in tools]
        assert "search" in names
        assert "create_page" not in names
        assert "delete_page" not in names

    async def test_write_agent_gets_read_and_write_tools(self):
        config = _make_config(
            default_permission=PermissionLevel.WRITE,
            discovered_tools=[
                {"name": "search", "description": "Search pages"},
                {"name": "create_page", "description": "Create page"},
                {"name": "delete_page", "description": "Delete page"},
            ],
        )
        tool_filter = ToolFilter()

        tools = tool_filter.filter_tools_for_agent(
            config.discovered_tools, config, "pm"
        )
        names = [t["name"] for t in tools]
        assert "search" in names
        assert "create_page" in names
        assert "delete_page" not in names

    async def test_disabled_tool_not_injected(self):
        config = _make_config(
            default_permission=PermissionLevel.FULL,
            tool_permissions=[
                ToolPermission(tool_name="delete_page", allowed=False),
            ],
            discovered_tools=[
                {"name": "search", "description": "Search pages"},
                {"name": "delete_page", "description": "Delete page"},
            ],
        )
        tool_filter = ToolFilter()

        tools = tool_filter.filter_tools_for_agent(
            config.discovered_tools, config, "cto"
        )
        names = [t["name"] for t in tools]
        assert "delete_page" not in names


# ---------------------------------------------------------------------------
# Tool call logging tests
# ---------------------------------------------------------------------------


class TestToolCallLogging:
    async def test_tool_execution_calls_client_manager(self):
        """Verify execute_tool routes through the client manager."""
        pytest.importorskip("cryptography", reason="cryptography not installed")
        from connections.agent_tools import AgentConnectionTools, AgentTool

        mock_manager = AsyncMock()
        mock_manager.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "OK"}],
                "is_error": False,
            }
        )

        agent_tools = AgentConnectionTools(mock_manager)
        tool = AgentTool(
            name="notion_search",
            description="Search Notion",
            input_schema={},
            connection_id="conn-1",
            original_tool_name="search",
            service="notion",
            display_name="Product Wiki",
        )

        result = await agent_tools.execute_tool(
            tool,
            {"query": "auth"},
            org_id="org-test",
            agent_role="researcher",
            pipeline_id="pipe-1",
        )

        # Verify the call was routed to the client manager
        mock_manager.call_tool.assert_called_once_with(
            "conn-1",
            "search",
            {"query": "auth"},
            org_id="org-test",
            agent_role="researcher",
            pipeline_id="pipe-1",
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Singleton pattern tests
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_pipeline_hooks_returns_same_instance(self):
        # Reset singleton
        import connections.pipeline_hooks as mod

        mod._hooks = None

        h1 = get_pipeline_hooks()
        h2 = get_pipeline_hooks()
        assert h1 is h2

        # Clean up
        mod._hooks = None
