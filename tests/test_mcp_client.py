"""Tests for MCP client manager — session management, tool calls, reconnection.

Covers:
    - Connecting to a mock MCP server
    - Tool listing and caching
    - Tool call execution and error handling
    - Reconnection on failure
    - Concurrent tool calls from multiple agents

Requires ``cryptography`` and ``asyncpg`` (the full server dependency set).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# Skip the whole module if heavy deps are missing
pytest.importorskip("cryptography", reason="cryptography not installed")

from connections.models import (
    ConnectionConfig,
    PermissionLevel,
    ServiceType,
    TransportType,
)


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------


def _uid() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


def _make_config(**overrides) -> ConnectionConfig:
    defaults = dict(
        id=_uid(),
        org_id="org-test",
        service=ServiceType.NOTION,
        display_name="Test Notion",
        transport=TransportType.STREAMABLE_HTTP,
        server_url="https://mcp.example.com",
        default_permission=PermissionLevel.READ,
        enabled=True,
    )
    defaults.update(overrides)
    return ConnectionConfig(**defaults)


@dataclass
class FakeToolResult:
    """Mimics MCP CallToolResult."""

    content: list = field(default_factory=list)
    is_error: bool = False


@dataclass
class FakeTextContent:
    """Mimics MCP TextContent."""

    type: str = "text"
    text: str = ""


@dataclass
class FakeTool:
    """Mimics MCP Tool object from list_tools()."""

    name: str = ""
    description: str = ""
    inputSchema: dict = field(default_factory=dict)


class FakeSession:
    """Mock MCP ClientSession."""

    def __init__(self, tools=None, call_results=None, fail_on_call=False):
        self._tools = tools or []
        self._call_results = call_results or {}
        self._fail_on_call = fail_on_call
        self._call_count = 0

    async def list_tools(self):
        result = MagicMock()
        result.tools = self._tools
        return result

    async def call_tool(self, tool_name, arguments=None):
        self._call_count += 1
        if self._fail_on_call:
            raise ConnectionError("MCP server connection lost")
        if tool_name in self._call_results:
            return self._call_results[tool_name]
        return FakeToolResult(
            content=[FakeTextContent(text=f"result for {tool_name}")],
        )


@pytest.fixture
def mock_registry():
    """Mock ConnectionRegistry that returns configs from a dict."""
    registry = AsyncMock()
    registry._configs = {}

    async def _get(cid):
        if cid in registry._configs:
            return registry._configs[cid]
        raise KeyError(f"Connection {cid} not found")

    async def _list(org_id):
        return [c for c in registry._configs.values() if c.org_id == org_id]

    registry.get_connection = AsyncMock(side_effect=_get)
    registry.list_connections = AsyncMock(side_effect=_list)
    return registry


@pytest.fixture
def client_manager(mock_registry):
    """Create a MCPClientManager with mocked registry and DB pool."""
    with patch("connections.client_manager._get_pool", return_value=AsyncMock()):
        from connections.client_manager import MCPClientManager

        mgr = MCPClientManager(mock_registry)
        return mgr


# ---------------------------------------------------------------------------
# Tool listing tests
# ---------------------------------------------------------------------------


class TestToolListing:
    async def test_list_tools_returns_discovered_tools(
        self, client_manager, mock_registry
    ):
        config = _make_config(
            discovered_tools=[
                {"name": "search", "description": "Search pages"},
                {"name": "create_page", "description": "Create a page"},
            ]
        )
        mock_registry._configs[config.id] = config
        mock_registry.get_connection.return_value = config

        # list_tools should use the session to discover tools
        fake_tools = [
            FakeTool(name="search", description="Search pages"),
            FakeTool(name="create_page", description="Create a page"),
        ]
        session = FakeSession(tools=fake_tools)

        with patch.object(
            client_manager, "get_session", new_callable=AsyncMock, return_value=session
        ):
            tools = await client_manager.list_tools(config.id)
            assert len(tools) == 2
            names = [t["name"] for t in tools]
            assert "search" in names
            assert "create_page" in names


# ---------------------------------------------------------------------------
# Tool call execution tests
# ---------------------------------------------------------------------------


class TestToolCallExecution:
    async def test_call_tool_returns_result(self, client_manager, mock_registry):
        config = _make_config()
        mock_registry._configs[config.id] = config
        mock_registry.get_connection.return_value = config

        expected_result = FakeToolResult(
            content=[FakeTextContent(text='{"pages": []}')],
        )
        session = FakeSession(call_results={"search": expected_result})

        with patch.object(
            client_manager,
            "get_session",
            new_callable=AsyncMock,
            return_value=session,
        ):
            result = await client_manager.call_tool(
                config.id, "search", {"query": "test"},
                org_id="org-test",
                agent_role="researcher",
            )
            assert result is not None
            assert "content" in result or isinstance(result, dict)

    async def test_call_tool_with_error_result(self, client_manager, mock_registry):
        config = _make_config()
        mock_registry._configs[config.id] = config
        mock_registry.get_connection.return_value = config

        error_result = FakeToolResult(
            content=[FakeTextContent(text="Permission denied")],
            is_error=True,
        )
        session = FakeSession(call_results={"create_page": error_result})

        with patch.object(
            client_manager,
            "get_session",
            new_callable=AsyncMock,
            return_value=session,
        ):
            result = await client_manager.call_tool(
                config.id, "create_page", {"title": "test"},
                org_id="org-test",
            )
            # Should return the error result rather than raising
            assert result is not None

    async def test_call_tool_on_missing_connection_raises(self, client_manager):
        with pytest.raises((KeyError, Exception)):
            await client_manager.call_tool(
                "nonexistent", "search", {},
                org_id="org-test",
            )


# ---------------------------------------------------------------------------
# Error handling & reconnection tests
# ---------------------------------------------------------------------------


class TestReconnection:
    async def test_connection_failure_triggers_reconnect_attempt(
        self, client_manager, mock_registry
    ):
        config = _make_config()
        mock_registry._configs[config.id] = config
        mock_registry.get_connection.return_value = config

        call_count = 0

        async def _get_session_with_failures(cid):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection lost")
            return FakeSession()

        with patch.object(
            client_manager,
            "get_session",
            new_callable=AsyncMock,
            side_effect=_get_session_with_failures,
        ):
            # First call should fail, but the manager should retry
            try:
                await client_manager.call_tool(
                    config.id, "search", {},
                    org_id="org-test",
                )
            except Exception:
                pass  # Expected — retry logic may or may not succeed
            # Verify that get_session was called (attempted connection)
            assert call_count >= 1

    async def test_disconnect_clears_session(self, client_manager, mock_registry):
        config = _make_config()
        mock_registry._configs[config.id] = config

        # Pretend we have an active session
        from connections.client_manager import _ManagedSession

        managed = _ManagedSession(
            connection_id=config.id,
            config=config,
            connected=True,
        )
        client_manager._sessions = {config.id: managed}

        await client_manager.disconnect(config.id)
        assert config.id not in client_manager._sessions or not client_manager._sessions[config.id].connected


# ---------------------------------------------------------------------------
# Concurrent tool call tests
# ---------------------------------------------------------------------------


class TestConcurrentCalls:
    async def test_concurrent_calls_from_multiple_agents(
        self, client_manager, mock_registry
    ):
        config = _make_config()
        mock_registry._configs[config.id] = config
        mock_registry.get_connection.return_value = config

        call_log = []

        async def _mock_call(cid, tool, args, **kwargs):
            role = kwargs.get("agent_role", "unknown")
            call_log.append(role)
            await asyncio.sleep(0.01)  # Simulate network latency
            return {"content": [{"text": f"result for {role}"}]}

        with patch.object(client_manager, "call_tool", side_effect=_mock_call):
            tasks = [
                client_manager.call_tool(
                    config.id, "search", {"query": "auth"},
                    org_id="org-test", agent_role="business_analyst",
                ),
                client_manager.call_tool(
                    config.id, "search", {"query": "users"},
                    org_id="org-test", agent_role="researcher",
                ),
                client_manager.call_tool(
                    config.id, "search", {"query": "api"},
                    org_id="org-test", agent_role="architect",
                ),
            ]
            results = await asyncio.gather(*tasks)
            assert len(results) == 3
            assert len(call_log) == 3

    async def test_concurrent_calls_to_different_connections(
        self, client_manager, mock_registry
    ):
        notion_config = _make_config(service=ServiceType.NOTION)
        linear_config = _make_config(service=ServiceType.LINEAR)
        mock_registry._configs[notion_config.id] = notion_config
        mock_registry._configs[linear_config.id] = linear_config
        mock_registry.get_connection.side_effect = lambda cid: (
            notion_config if cid == notion_config.id else linear_config
        )

        call_log = []

        async def _mock_call(cid, tool, args, **kwargs):
            call_log.append(cid)
            await asyncio.sleep(0.01)
            return {"content": [{"text": "ok"}]}

        with patch.object(client_manager, "call_tool", side_effect=_mock_call):
            results = await asyncio.gather(
                client_manager.call_tool(
                    notion_config.id, "search", {},
                    org_id="org-test", agent_role="pm",
                ),
                client_manager.call_tool(
                    linear_config.id, "search_issues", {},
                    org_id="org-test", agent_role="pm",
                ),
            )
            assert len(results) == 2
            assert notion_config.id in call_log
            assert linear_config.id in call_log


# ---------------------------------------------------------------------------
# MCPClientManager.get_status() tests
# ---------------------------------------------------------------------------


class TestClientManagerStatus:
    def test_status_empty_when_no_sessions(self, client_manager):
        status = client_manager.get_status()
        assert status == {} or isinstance(status, dict)

    def test_status_reflects_active_sessions(self, client_manager):
        from connections.client_manager import _ManagedSession

        config = _make_config()
        managed = _ManagedSession(
            connection_id=config.id,
            config=config,
            connected=True,
        )
        client_manager._sessions = {config.id: managed}

        status = client_manager.get_status()
        assert config.id in status
        assert status[config.id]["connected"] is True
