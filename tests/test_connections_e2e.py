"""End-to-end test for MCP connections through a full pipeline lifecycle.

Simulates a complete pipeline with Notion + Linear connected:
    1. Connect Notion (test workspace) and Linear (test project)
    2. Start pipeline: "Add a user preferences API endpoint"
    3. Verify BA searches Notion for existing specs
    4. Verify PM creates Linear tickets
    5. Verify Engineer references tickets while coding
    6. Verify QA creates bug tickets for findings
    7. Verify pipeline completion updates ticket statuses

This test uses mocked MCP servers — it does not require real Notion/Linear
credentials.  Set FORGE_E2E=1 to run.
"""

from __future__ import annotations

import asyncio
import json
import os
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
from connections.pipeline_hooks import ConnectionPipelineHooks
from connections.tool_filter import ToolFilter

# Skip unless E2E flag is set
pytestmark = pytest.mark.skipif(
    os.environ.get("FORGE_E2E") != "1",
    reason="End-to-end test — set FORGE_E2E=1 to run",
)

# Lazy imports for modules that need heavy deps
AgentConnectionTools = None
AgentTool = None


# ---------------------------------------------------------------------------
# Mock MCP infrastructure
# ---------------------------------------------------------------------------

_CALL_LOG: list[dict] = []
"""Global log of all tool calls made during the e2e test."""


def _uid() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}"


@dataclass
class MockNotionServer:
    """Simulates Notion MCP server responses."""

    pages: dict[str, str] = field(default_factory=dict)

    def handle_call(self, tool_name: str, arguments: dict) -> dict:
        if tool_name == "search":
            query = arguments.get("query", "").lower()
            matches = [
                {"title": t, "snippet": c[:200]}
                for t, c in self.pages.items()
                if query[:20] in t.lower() or query[:20] in c.lower()
            ]
            return {
                "content": [{"text": json.dumps(matches[:5])}],
                "is_error": False,
            }
        elif tool_name == "create_page":
            title = arguments.get("title", "Untitled")
            content = arguments.get("content", "")
            self.pages[title] = content
            return {
                "content": [{"text": json.dumps({"id": _uid(), "title": title})}],
                "is_error": False,
            }
        return {"content": [{"text": "Unknown tool"}], "is_error": True}


@dataclass
class MockLinearServer:
    """Simulates Linear MCP server responses."""

    issues: list[dict] = field(default_factory=list)

    def handle_call(self, tool_name: str, arguments: dict) -> dict:
        if tool_name == "search_issues":
            query = arguments.get("query", "").lower()
            matches = [
                i for i in self.issues
                if query[:20] in i.get("title", "").lower()
            ]
            return {
                "content": [{"text": json.dumps(matches[:10])}],
                "is_error": False,
            }
        elif tool_name == "create_issue":
            issue = {
                "id": _uid(),
                "title": arguments.get("title", ""),
                "description": arguments.get("description", ""),
                "priority": arguments.get("priority", "medium"),
                "status": "backlog",
            }
            self.issues.append(issue)
            return {
                "content": [{"text": json.dumps(issue)}],
                "is_error": False,
            }
        elif tool_name == "update_issue":
            issue_id = arguments.get("issue_id", "")
            status = arguments.get("status", "")
            for issue in self.issues:
                if issue["id"] == issue_id or issue["title"].startswith(f"[{issue_id}]"):
                    issue["status"] = status
                    return {
                        "content": [{"text": json.dumps(issue)}],
                        "is_error": False,
                    }
            return {"content": [{"text": "Issue not found"}], "is_error": True}
        return {"content": [{"text": "Unknown tool"}], "is_error": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def notion_server():
    server = MockNotionServer()
    server.pages = {
        "Authentication Architecture": (
            "Our auth system uses JWT tokens with refresh rotation. "
            "User preferences are currently stored in a simple key-value "
            "table but need migration to a proper schema."
        ),
        "API Conventions": (
            "All endpoints follow REST conventions. Use kebab-case URLs. "
            "Return 200 for success, 201 for creation, 404 for not found."
        ),
    }
    return server


@pytest.fixture
def linear_server():
    server = MockLinearServer()
    server.issues = [
        {
            "id": "existing-1",
            "title": "PREF-100: User preferences table migration",
            "description": "Migrate key-value to typed schema",
            "status": "in_progress",
        },
    ]
    return server


@pytest.fixture
def notion_config():
    return ConnectionConfig(
        id="conn-notion-e2e",
        org_id="org-e2e",
        service=ServiceType.NOTION,
        display_name="Product Wiki",
        transport=TransportType.STREAMABLE_HTTP,
        server_url="https://mcp.notion.com/mcp",
        default_permission=PermissionLevel.READ,
        agent_permissions={
            "business_analyst": PermissionLevel.WRITE,
            "pm": PermissionLevel.WRITE,
        },
        enabled=True,
        discovered_tools=[
            {"name": "search", "description": "Search pages by query"},
            {"name": "get_page", "description": "Read a page by ID"},
            {"name": "create_page", "description": "Create a new page"},
            {"name": "update_page", "description": "Update an existing page"},
            {"name": "delete_page", "description": "Delete a page"},
        ],
    )


@pytest.fixture
def linear_config():
    return ConnectionConfig(
        id="conn-linear-e2e",
        org_id="org-e2e",
        service=ServiceType.LINEAR,
        display_name="Engineering Board",
        transport=TransportType.SSE,
        server_url="https://mcp.linear.app/sse",
        default_permission=PermissionLevel.READ,
        agent_permissions={
            "pm": PermissionLevel.WRITE,
            "qa": PermissionLevel.WRITE,
        },
        enabled=True,
        discovered_tools=[
            {"name": "search_issues", "description": "Search Linear issues"},
            {"name": "get_issue", "description": "Get issue by ID"},
            {"name": "create_issue", "description": "Create a new issue"},
            {"name": "update_issue", "description": "Update issue status"},
            {"name": "delete_issue", "description": "Delete an issue"},
        ],
    )


@pytest.fixture
def mock_manager(notion_server, linear_server, notion_config, linear_config):
    """Client manager that routes calls to mock servers."""
    manager = AsyncMock()

    async def _call_tool(connection_id, tool_name, arguments, **kwargs):
        entry = {
            "connection_id": connection_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "agent_role": kwargs.get("agent_role"),
            "pipeline_id": kwargs.get("pipeline_id"),
        }
        _CALL_LOG.append(entry)

        if connection_id == notion_config.id:
            return notion_server.handle_call(tool_name, arguments)
        elif connection_id == linear_config.id:
            return linear_server.handle_call(tool_name, arguments)
        return {"content": [{"text": "Unknown connection"}], "is_error": True}

    manager.call_tool = AsyncMock(side_effect=_call_tool)
    return manager


@pytest.fixture
def hooks(mock_manager, notion_config, linear_config):
    h = ConnectionPipelineHooks()
    h._manager = mock_manager

    # Mock registry to return our test connections
    registry = AsyncMock()

    async def _list_connections(org_id):
        return [notion_config, linear_config]

    registry.list_connections = AsyncMock(side_effect=_list_connections)
    h._registry = registry

    return h


@pytest.fixture(autouse=True)
def _clear_call_log():
    _CALL_LOG.clear()
    yield
    _CALL_LOG.clear()


# ---------------------------------------------------------------------------
# E2E test
# ---------------------------------------------------------------------------


class TestConnectionsE2E:
    """Full pipeline lifecycle with Notion + Linear connected."""

    PIPELINE_ID = "pipe-e2e-prefs"
    ORG_ID = "org-e2e"
    SPEC = "Add a user preferences API endpoint that allows users to store and retrieve their display preferences (theme, language, timezone)."

    async def test_full_pipeline_lifecycle(
        self,
        hooks,
        notion_config,
        linear_config,
        notion_server,
        linear_server,
        mock_manager,
    ):
        """
        Step 1: Pipeline start — BA searches Notion for existing specs
        """
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            context = await hooks.on_pipeline_start(
                self.PIPELINE_ID, self.ORG_ID, self.SPEC,
            )

        # Verify Notion was searched
        notion_searches = [
            c for c in _CALL_LOG
            if c["connection_id"] == notion_config.id and c["tool_name"] == "search"
        ]
        assert len(notion_searches) >= 1, "BA should search Notion for related docs"
        assert len(context["notion_pages"]) >= 1, "Should find related Notion pages"

        # Verify Linear was searched for related tickets
        linear_searches = [
            c for c in _CALL_LOG
            if c["connection_id"] == linear_config.id
            and c["tool_name"] == "search_issues"
        ]
        assert len(linear_searches) >= 1, "Should search Linear for related tickets"

        """
        Step 2: BA completes — creates Notion spec page
        """
        ba_output = {
            "product_name": "User Preferences API",
            "product_vision": "Allow users to customize their experience",
            "user_stories": [
                {"id": "US-001", "action": "Set theme preference"},
                {"id": "US-002", "action": "Set language preference"},
                {"id": "US-003", "action": "Set timezone"},
            ],
        }

        _CALL_LOG.clear()
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            await hooks.on_stage_complete(
                self.PIPELINE_ID, self.ORG_ID, "business_analysis", ba_output,
            )

        # Verify Notion spec page was created
        notion_creates = [
            c for c in _CALL_LOG
            if c["connection_id"] == notion_config.id
            and c["tool_name"] == "create_page"
        ]
        assert len(notion_creates) == 1, "Should create Notion spec page after BA"
        assert "User Preferences" in notion_creates[0]["arguments"]["title"]
        assert "User Preferences API" in notion_server.pages.get(
            "[Pipeline] User Preferences API", ""
        ) or len(notion_server.pages) > 2

        """
        Step 3: PM completes — creates Linear tickets
        """
        pm_output = {
            "tickets": [
                {
                    "ticket_key": "FORGE-1",
                    "title": "Create preferences DB schema",
                    "description": "Add preferences table with columns for theme, language, timezone",
                    "priority": "high",
                },
                {
                    "ticket_key": "FORGE-2",
                    "title": "Add GET /preferences endpoint",
                    "description": "Return user preferences, default if not set",
                    "priority": "high",
                },
                {
                    "ticket_key": "FORGE-3",
                    "title": "Add PUT /preferences endpoint",
                    "description": "Update user preferences with validation",
                    "priority": "medium",
                },
            ],
        }

        _CALL_LOG.clear()
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            await hooks.on_stage_complete(
                self.PIPELINE_ID, self.ORG_ID, "pm", pm_output,
            )

        # Verify Linear tickets were created
        linear_creates = [
            c for c in _CALL_LOG
            if c["connection_id"] == linear_config.id
            and c["tool_name"] == "create_issue"
        ]
        assert len(linear_creates) == 3, "PM should create 3 Linear tickets"
        assert any(
            "FORGE-1" in c["arguments"]["title"] for c in linear_creates
        ), "Tickets should include ticket keys"

        """
        Step 4: Verify Engineer can access tools via ToolFilter
        """
        tool_filter = ToolFilter()

        # Engineer has READ default for both Notion and Linear
        eng_notion_tools = tool_filter.filter_tools_for_agent(
            notion_config.discovered_tools, notion_config, "engineer"
        )
        eng_linear_tools = tool_filter.filter_tools_for_agent(
            linear_config.discovered_tools, linear_config, "engineer"
        )

        eng_notion_names = [t["name"] for t in eng_notion_tools]
        assert "search" in eng_notion_names, "Engineer should read Notion"
        assert "create_page" not in eng_notion_names, "Engineer should NOT write Notion"

        eng_linear_names = [t["name"] for t in eng_linear_tools]
        assert "search_issues" in eng_linear_names, "Engineer should read Linear"
        assert "get_issue" in eng_linear_names, "Engineer should read Linear issues"
        assert "create_issue" not in eng_linear_names, "Engineer should NOT write Linear"

        """
        Step 5: QA finds issues — creates bug tickets
        """
        qa_output = {
            "ticket_key": "FORGE-2",
            "verdict": "needs_revision",
            "comments": [
                {
                    "file_path": "src/preferences/service.ts",
                    "line": 28,
                    "severity": "critical",
                    "comment": "SQL injection: user input concatenated into query string",
                },
                {
                    "file_path": "src/preferences/service.ts",
                    "line": 45,
                    "severity": "error",
                    "comment": "Missing input validation for timezone format",
                },
                {
                    "file_path": "src/preferences/service.ts",
                    "line": 5,
                    "severity": "info",
                    "comment": "Good separation of concerns",
                },
            ],
        }

        _CALL_LOG.clear()
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            await hooks.on_stage_complete(
                self.PIPELINE_ID, self.ORG_ID, "qa_review", qa_output,
            )

        # Verify bug tickets were created for critical + error findings
        bug_creates = [
            c for c in _CALL_LOG
            if c["connection_id"] == linear_config.id
            and c["tool_name"] == "create_issue"
        ]
        assert len(bug_creates) == 2, "QA should create 2 bug tickets (critical + error)"
        assert any(
            "SQL injection" in c["arguments"]["title"] for c in bug_creates
        )

        """
        Step 6: Pipeline completes — updates ticket statuses
        """
        # Get IDs of tickets created by PM
        pm_ticket_titles = [
            f"[{t['ticket_key']}] {t['title']}" for t in pm_output["tickets"]
        ]

        result = {
            "name": "User Preferences API",
            "completed_tickets": ["FORGE-1", "FORGE-2", "FORGE-3"],
            "total_cost_usd": 2.45,
        }

        _CALL_LOG.clear()
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            await hooks.on_pipeline_complete(
                self.PIPELINE_ID, self.ORG_ID, result,
            )

        # Verify tickets were updated to Done
        linear_updates = [
            c for c in _CALL_LOG
            if c["connection_id"] == linear_config.id
            and c["tool_name"] == "update_issue"
        ]
        assert len(linear_updates) == 3, "Should update all 3 tickets to Done"
        for update in linear_updates:
            assert update["arguments"]["status"] == "done"

        # Verify Notion completion page was created
        notion_completes = [
            c for c in _CALL_LOG
            if c["connection_id"] == notion_config.id
            and c["tool_name"] == "create_page"
        ]
        assert len(notion_completes) == 1, "Should create Notion completion page"
        assert "Pipeline Complete" in notion_completes[0]["arguments"]["title"]

    async def test_tool_call_audit_log_complete(
        self,
        hooks,
        notion_config,
        linear_config,
        mock_manager,
    ):
        """Verify that every tool call was logged."""
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            await hooks.on_pipeline_start(
                self.PIPELINE_ID, self.ORG_ID, self.SPEC,
            )

        # Every tool call should have pipeline_id set
        for entry in _CALL_LOG:
            assert entry["pipeline_id"] == self.PIPELINE_ID, (
                f"Tool call to {entry['tool_name']} missing pipeline_id"
            )

    async def test_pipeline_failure_creates_ticket_and_notion_page(
        self,
        hooks,
        linear_config,
        notion_config,
        mock_manager,
    ):
        """Verify failure handling creates both a bug ticket and Notion page."""
        error = {
            "message": "Architect agent exceeded budget limit ($5.00)",
            "stage": "architecture",
        }

        _CALL_LOG.clear()
        with patch(
            "connections.pipeline_hooks.stream_agent_log",
            new_callable=AsyncMock,
        ):
            await hooks.on_pipeline_failure(
                self.PIPELINE_ID, self.ORG_ID, error,
            )

        # Bug ticket in Linear
        bug_tickets = [
            c for c in _CALL_LOG
            if c["connection_id"] == linear_config.id
            and c["tool_name"] == "create_issue"
        ]
        assert len(bug_tickets) >= 1, "Should create failure bug ticket"
        assert "Pipeline Failed" in bug_tickets[0]["arguments"]["title"]
        assert bug_tickets[0]["arguments"]["priority"] == "urgent"

        # Status page in Notion
        notion_pages = [
            c for c in _CALL_LOG
            if c["connection_id"] == notion_config.id
            and c["tool_name"] == "create_page"
        ]
        assert len(notion_pages) >= 1, "Should create Notion failure page"
        assert "BLOCKED" in notion_pages[0]["arguments"]["title"]
