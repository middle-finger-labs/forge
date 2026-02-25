"""MCP client — manages sessions to external MCP servers.

Supports all three MCP transport types:
- stdio: spawns a subprocess (e.g. ``npx -y @notionhq/notion-mcp-server``)
- sse: connects to a Server-Sent Events endpoint
- streamable_http: connects via Streamable HTTP (the newer MCP transport)

Usage::

    from connections.client import create_mcp_session

    async with create_mcp_session(config, credentials) as session:
        tools = await session.list_tools()
        result = await session.call_tool("notion_search", {"query": "roadmap"})
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog

from connections.models import ConnectionConfig, TransportType

log = structlog.get_logger().bind(component="connections.client")


@asynccontextmanager
async def create_mcp_session(
    config: ConnectionConfig,
    credentials: str | None = None,
) -> AsyncIterator:
    """Create and yield an MCP ClientSession for the given connection config.

    The session is automatically closed when the context manager exits.
    """
    from mcp import ClientSession

    if config.transport == TransportType.STDIO:
        async with _stdio_session(config, credentials) as session:
            await session.initialize()
            yield session

    elif config.transport == TransportType.SSE:
        async with _sse_session(config, credentials) as session:
            await session.initialize()
            yield session

    elif config.transport == TransportType.STREAMABLE_HTTP:
        async with _streamable_http_session(config, credentials) as session:
            await session.initialize()
            yield session

    else:
        raise ValueError(f"Unsupported transport: {config.transport}")


# ---------------------------------------------------------------------------
# Transport-specific session factories
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _stdio_session(
    config: ConnectionConfig,
    credentials: str | None,
) -> AsyncIterator:
    """Spawn a stdio MCP server subprocess and connect."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not config.command:
        raise ValueError(f"stdio transport requires 'command' for {config.display_name}")

    # Build environment: inherit current env + connection-specific vars + credentials
    env = {**os.environ, **(config.env or {})}
    if credentials:
        # Convention: pass token as the service-specific env var
        env_key = _credential_env_key(config)
        env[env_key] = credentials

    server_params = StdioServerParameters(
        command=config.command,
        args=config.args or [],
        env=env,
    )

    log.info(
        "starting stdio MCP server",
        command=config.command,
        args=config.args,
        connection=config.display_name,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            yield session


@asynccontextmanager
async def _sse_session(
    config: ConnectionConfig,
    credentials: str | None,
) -> AsyncIterator:
    """Connect to an SSE MCP server."""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    if not config.server_url:
        raise ValueError(f"SSE transport requires 'server_url' for {config.display_name}")

    headers: dict[str, str] = {}
    if credentials:
        headers["Authorization"] = f"Bearer {credentials}"

    log.info(
        "connecting to SSE MCP server",
        url=config.server_url,
        connection=config.display_name,
    )

    async with sse_client(config.server_url, headers=headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            yield session


@asynccontextmanager
async def _streamable_http_session(
    config: ConnectionConfig,
    credentials: str | None,
) -> AsyncIterator:
    """Connect to a Streamable HTTP MCP server."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    if not config.server_url:
        raise ValueError(
            f"Streamable HTTP transport requires 'server_url' for {config.display_name}"
        )

    headers: dict[str, str] = {}
    if credentials:
        headers["Authorization"] = f"Bearer {credentials}"

    log.info(
        "connecting to Streamable HTTP MCP server",
        url=config.server_url,
        connection=config.display_name,
    )

    async with streamablehttp_client(
        config.server_url, headers=headers
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _credential_env_key(config: ConnectionConfig) -> str:
    """Return the environment variable name for passing credentials to a stdio server."""
    env_keys = {
        "notion": "OPENAPI_MCP_HEADERS",
        "linear": "LINEAR_API_KEY",
        "figma": "FIGMA_PERSONAL_ACCESS_TOKEN",
        "jira": "ATLASSIAN_API_TOKEN",
        "google_drive": "GOOGLE_APPLICATION_CREDENTIALS",
    }
    return env_keys.get(config.service.value, f"{config.service.value.upper()}_API_TOKEN")
