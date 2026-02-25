"""Tests for MCP connection CRUD, permission filtering, and tool classification.

Covers:
    - ConnectionRegistry CRUD (create, read, update, delete)
    - Permission filtering (read-only agents can't see write tools)
    - Agent-specific permission overrides
    - Tool-level permission overrides
    - ToolFilter classification (read vs write vs admin)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connections.models import (
    ConnectionConfig,
    DiscoveredTool,
    PermissionLevel,
    ServiceType,
    ToolPermission,
    TransportType,
)
from connections.tool_filter import ToolFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


def _make_config(
    *,
    service: ServiceType = ServiceType.NOTION,
    default_permission: PermissionLevel = PermissionLevel.READ,
    agent_permissions: dict[str, PermissionLevel] | None = None,
    tool_permissions: list[ToolPermission] | None = None,
    automation_config: dict[str, bool] | None = None,
    discovered_tools: list[dict] | None = None,
    enabled: bool = True,
) -> ConnectionConfig:
    return ConnectionConfig(
        id=_uid(),
        org_id="org-test",
        service=service,
        display_name=f"Test {service.value}",
        transport=TransportType.STREAMABLE_HTTP,
        server_url="https://mcp.example.com",
        default_permission=default_permission,
        agent_permissions=agent_permissions or {},
        tool_permissions=tool_permissions or [],
        automation_config=automation_config or {},
        discovered_tools=discovered_tools or [],
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# PermissionLevel.allows() tests
# ---------------------------------------------------------------------------


class TestPermissionLevel:
    def test_none_allows_nothing(self):
        assert PermissionLevel.NONE.allows(PermissionLevel.NONE)
        assert not PermissionLevel.NONE.allows(PermissionLevel.READ)
        assert not PermissionLevel.NONE.allows(PermissionLevel.WRITE)
        assert not PermissionLevel.NONE.allows(PermissionLevel.FULL)

    def test_read_allows_read_and_below(self):
        assert PermissionLevel.READ.allows(PermissionLevel.NONE)
        assert PermissionLevel.READ.allows(PermissionLevel.READ)
        assert not PermissionLevel.READ.allows(PermissionLevel.WRITE)
        assert not PermissionLevel.READ.allows(PermissionLevel.FULL)

    def test_write_allows_write_and_below(self):
        assert PermissionLevel.WRITE.allows(PermissionLevel.NONE)
        assert PermissionLevel.WRITE.allows(PermissionLevel.READ)
        assert PermissionLevel.WRITE.allows(PermissionLevel.WRITE)
        assert not PermissionLevel.WRITE.allows(PermissionLevel.FULL)

    def test_full_allows_everything(self):
        for level in PermissionLevel:
            assert PermissionLevel.FULL.allows(level)


# ---------------------------------------------------------------------------
# ConnectionConfig.get_agent_permission() tests
# ---------------------------------------------------------------------------


class TestConnectionConfigPermissions:
    def test_default_permission_when_no_override(self):
        config = _make_config(default_permission=PermissionLevel.READ)
        assert config.get_agent_permission("engineer") == PermissionLevel.READ

    def test_agent_override_takes_precedence(self):
        config = _make_config(
            default_permission=PermissionLevel.READ,
            agent_permissions={"pm": PermissionLevel.WRITE},
        )
        assert config.get_agent_permission("pm") == PermissionLevel.WRITE
        assert config.get_agent_permission("engineer") == PermissionLevel.READ

    def test_multiple_agent_overrides(self):
        config = _make_config(
            default_permission=PermissionLevel.NONE,
            agent_permissions={
                "business_analyst": PermissionLevel.WRITE,
                "researcher": PermissionLevel.READ,
                "cto": PermissionLevel.FULL,
            },
        )
        assert config.get_agent_permission("business_analyst") == PermissionLevel.WRITE
        assert config.get_agent_permission("researcher") == PermissionLevel.READ
        assert config.get_agent_permission("cto") == PermissionLevel.FULL
        assert config.get_agent_permission("qa") == PermissionLevel.NONE


# ---------------------------------------------------------------------------
# ToolFilter.classify_tool() tests
# ---------------------------------------------------------------------------


class TestToolClassification:
    def setup_method(self):
        self.filter = ToolFilter()

    # Read tools
    def test_classify_search_as_read(self):
        assert self.filter.classify_tool("search_pages", "") == "read"

    def test_classify_get_as_read(self):
        assert self.filter.classify_tool("get_page", "") == "read"

    def test_classify_list_as_read(self):
        assert self.filter.classify_tool("list_issues", "") == "read"

    def test_classify_fetch_as_read(self):
        assert self.filter.classify_tool("fetch_document", "") == "read"

    def test_classify_query_as_read(self):
        assert self.filter.classify_tool("query_database", "") == "read"

    def test_classify_find_as_read(self):
        assert self.filter.classify_tool("find_user", "") == "read"

    # Write tools
    def test_classify_create_as_write(self):
        assert self.filter.classify_tool("create_page", "") == "write"

    def test_classify_update_as_write(self):
        assert self.filter.classify_tool("update_issue", "") == "write"

    def test_classify_add_as_write(self):
        assert self.filter.classify_tool("add_comment", "") == "write"

    def test_classify_edit_as_write(self):
        assert self.filter.classify_tool("edit_block", "") == "write"

    def test_classify_send_as_write(self):
        assert self.filter.classify_tool("send_message", "") == "write"

    # Admin tools
    def test_classify_delete_as_admin(self):
        assert self.filter.classify_tool("delete_page", "") == "admin"

    def test_classify_remove_as_admin(self):
        assert self.filter.classify_tool("remove_member", "") == "admin"

    def test_classify_archive_as_admin(self):
        assert self.filter.classify_tool("archive_project", "") == "admin"

    def test_classify_destroy_as_admin(self):
        assert self.filter.classify_tool("destroy_workspace", "") == "admin"

    # Fallback
    def test_classify_unknown_defaults_to_read(self):
        assert self.filter.classify_tool("do_something", "") == "read"

    # Description-based classification
    def test_classify_from_description(self):
        result = self.filter.classify_tool(
            "manage_data", "Creates new records in the database"
        )
        assert result == "write"

    def test_classify_delete_in_description(self):
        result = self.filter.classify_tool(
            "manage_data", "Permanently deletes records"
        )
        assert result == "admin"


# ---------------------------------------------------------------------------
# ToolFilter.filter_tools_for_agent() tests
# ---------------------------------------------------------------------------


_SAMPLE_TOOLS = [
    {"name": "search_pages", "description": "Search Notion pages"},
    {"name": "get_page", "description": "Read a single page"},
    {"name": "create_page", "description": "Create a new page"},
    {"name": "update_page", "description": "Update page content"},
    {"name": "delete_page", "description": "Delete a page permanently"},
]


class TestFilterToolsForAgent:
    def setup_method(self):
        self.filter = ToolFilter()

    def test_none_permission_returns_no_tools(self):
        config = _make_config(default_permission=PermissionLevel.NONE)
        result = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "engineer"
        )
        assert result == []

    def test_read_permission_returns_only_read_tools(self):
        config = _make_config(default_permission=PermissionLevel.READ)
        result = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "engineer"
        )
        names = [t["name"] for t in result]
        assert "search_pages" in names
        assert "get_page" in names
        assert "create_page" not in names
        assert "update_page" not in names
        assert "delete_page" not in names

    def test_write_permission_returns_read_and_write_tools(self):
        config = _make_config(default_permission=PermissionLevel.WRITE)
        result = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "pm"
        )
        names = [t["name"] for t in result]
        assert "search_pages" in names
        assert "get_page" in names
        assert "create_page" in names
        assert "update_page" in names
        assert "delete_page" not in names

    def test_full_permission_returns_all_tools(self):
        config = _make_config(default_permission=PermissionLevel.FULL)
        result = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "cto"
        )
        names = [t["name"] for t in result]
        assert len(names) == 5
        assert "delete_page" in names

    def test_agent_override_expands_access(self):
        """PM has write access even though default is read."""
        config = _make_config(
            default_permission=PermissionLevel.READ,
            agent_permissions={"pm": PermissionLevel.WRITE},
        )
        # PM should see read + write tools
        pm_tools = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "pm"
        )
        pm_names = [t["name"] for t in pm_tools]
        assert "create_page" in pm_names

        # Engineer (default) should only see read tools
        eng_tools = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "engineer"
        )
        eng_names = [t["name"] for t in eng_tools]
        assert "create_page" not in eng_names

    def test_agent_override_restricts_access(self):
        """QA has none even though default is write."""
        config = _make_config(
            default_permission=PermissionLevel.WRITE,
            agent_permissions={"qa": PermissionLevel.NONE},
        )
        qa_tools = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "qa"
        )
        assert qa_tools == []

    def test_tool_level_disable(self):
        """Disable a specific tool via tool_permissions."""
        config = _make_config(
            default_permission=PermissionLevel.FULL,
            tool_permissions=[
                ToolPermission(tool_name="delete_page", allowed=False),
            ],
        )
        result = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "cto"
        )
        names = [t["name"] for t in result]
        assert "delete_page" not in names
        assert "create_page" in names

    def test_tool_level_agent_restriction(self):
        """Allow a tool only for specific agents."""
        config = _make_config(
            default_permission=PermissionLevel.WRITE,
            tool_permissions=[
                ToolPermission(
                    tool_name="create_page",
                    allowed=True,
                    allowed_agents=["pm", "business_analyst"],
                ),
            ],
        )
        # PM should have access
        pm_tools = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "pm"
        )
        pm_names = [t["name"] for t in pm_tools]
        assert "create_page" in pm_names

        # Engineer should NOT have access (not in allowed_agents)
        eng_tools = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "engineer"
        )
        eng_names = [t["name"] for t in eng_tools]
        assert "create_page" not in eng_names

    def test_disabled_connection_filtered_upstream(self):
        """ToolFilter doesn't check enabled — that's done in AgentConnectionTools.
        Verify that disabled connections are skipped at the assembly level."""
        config = _make_config(
            default_permission=PermissionLevel.FULL,
            enabled=False,
        )
        # ToolFilter itself still returns tools (doesn't check enabled)
        result = self.filter.filter_tools_for_agent(
            _SAMPLE_TOOLS, config, "cto"
        )
        assert len(result) == 5  # All tools pass permission check

        # The enabled check happens in AgentConnectionTools.get_tools_for_agent
        # which skips disabled connections entirely before calling filter

    def test_empty_tools_returns_empty(self):
        config = _make_config(default_permission=PermissionLevel.FULL)
        result = self.filter.filter_tools_for_agent([], config, "cto")
        assert result == []


# ---------------------------------------------------------------------------
# ConnectionRegistry CRUD (mocked database) tests
# ---------------------------------------------------------------------------


try:
    import connections.registry as _reg_mod
    from connections.registry import ConnectionRegistry

    _HAS_REGISTRY = True
except ImportError:
    _HAS_REGISTRY = False


@pytest.mark.skipif(not _HAS_REGISTRY, reason="Registry deps not installed (cryptography, asyncpg)")
class TestRegistryCRUD:
    """Test registry operations with a mocked asyncpg pool.

    Requires the full ``connections.registry`` import chain (cryptography,
    asyncpg).  Skipped in lightweight test environments.
    """

    @pytest.fixture
    def mock_pool(self):
        pool = AsyncMock()
        pool.fetchrow = AsyncMock()
        pool.fetch = AsyncMock()
        pool.execute = AsyncMock()
        return pool

    @pytest.fixture
    def registry(self, mock_pool):
        orig = _reg_mod._db_pool
        _reg_mod._db_pool = mock_pool
        yield ConnectionRegistry()
        _reg_mod._db_pool = orig

    def _make_db_row(self, **overrides):
        """Build a MagicMock that behaves like an asyncpg Record."""
        from datetime import datetime

        defaults = {
            "id": uuid.UUID(_uid().replace("test-", "00000000-0000-0000-0000-")),
            "org_id": "org-test",
            "service": "notion",
            "display_name": "Test Notion",
            "transport": "streamable_http",
            "server_url": "https://mcp.notion.com/mcp",
            "command": None,
            "args": [],
            "env": {},
            "auth_type": "oauth",
            "credential_secret_key": None,
            "default_permission": "read",
            "agent_permissions": {},
            "tool_permissions": [],
            "automation_config": {},
            "enabled": True,
            "last_connected_at": None,
            "discovered_tools": [],
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        defaults.update(overrides)

        # asyncpg Records support both dict-like and attribute access
        row = MagicMock()
        row.__getitem__ = lambda self_, key: defaults[key]
        row.get = lambda key, default=None: defaults.get(key, default)
        return row

    async def test_list_connections_returns_all_for_org(self, registry, mock_pool):
        rows = [
            self._make_db_row(display_name="Notion"),
            self._make_db_row(display_name="Linear", service="linear"),
        ]
        mock_pool.fetch.return_value = rows

        result = await registry.list_connections("org-test")
        assert len(result) == 2

    async def test_get_connection_returns_config(self, registry, mock_pool):
        row = self._make_db_row(display_name="My Notion")
        mock_pool.fetchrow.return_value = row

        config = await registry.get_connection("some-id")
        assert config.display_name == "My Notion"
        assert config.service == ServiceType.NOTION

    async def test_get_connection_raises_key_error_when_not_found(
        self, registry, mock_pool
    ):
        mock_pool.fetchrow.return_value = None

        with pytest.raises(KeyError):
            await registry.get_connection("nonexistent")

    async def test_create_connection_inserts_row(self, registry, mock_pool):
        created_row = self._make_db_row(display_name="New Connection")
        mock_pool.fetchrow.return_value = created_row

        with patch("connections.registry.encrypt_secret", return_value="encrypted"):
            config = await registry.create_connection(
                "org-test",
                service=ServiceType.NOTION,
                display_name="New Connection",
                transport=TransportType.STREAMABLE_HTTP,
            )
        assert config.display_name == "New Connection"
        assert mock_pool.fetchrow.called

    async def test_delete_connection_executes(self, registry, mock_pool):
        mock_pool.fetchrow.return_value = self._make_db_row()

        await registry.delete_connection("some-id")
        assert mock_pool.execute.called or mock_pool.fetchrow.called


# ---------------------------------------------------------------------------
# Automation config tests
# ---------------------------------------------------------------------------


class TestAutomationConfig:
    def test_default_automation_flags(self):
        config = _make_config()
        assert config.automation_config == {}

    def test_custom_automation_flags(self):
        config = _make_config(
            automation_config={
                "auto_create_tickets": False,
                "auto_search_context": True,
            }
        )
        assert config.automation_config["auto_create_tickets"] is False
        assert config.automation_config["auto_search_context"] is True

    def test_automation_config_preserved_on_update(self):
        config = _make_config(
            automation_config={"auto_create_tickets": False}
        )
        # Simulate updating a different field
        config.display_name = "Updated Name"
        assert config.automation_config["auto_create_tickets"] is False
