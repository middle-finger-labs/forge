"""MCP Client Manager — manages active MCP client sessions at runtime.

One MCPClientManager instance per worker process.  Sessions are lazily
created on first tool call and kept alive with periodic health checks.
Failed connections are retried with exponential backoff.

Usage::

    from connections.client_manager import MCPClientManager
    from connections.registry import ConnectionRegistry

    registry = ConnectionRegistry()
    manager = MCPClientManager(registry)

    # Call a tool (lazy-connects if needed)
    result = await manager.call_tool(
        connection_id="uuid",
        tool_name="notion_search",
        arguments={"query": "roadmap"},
        org_id="org-123",
        agent_role="ba",
        pipeline_id="pipeline-456",
    )

    # Graceful shutdown
    await manager.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import structlog

from connections.models import (
    ConnectionConfig,
    PermissionLevel,
    ServiceType,
    TransportType,
)
from connections.registry import ConnectionRegistry

log = structlog.get_logger().bind(component="connections.client_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HEALTH_CHECK_INTERVAL = 60  # seconds between health pings
_MAX_RECONNECT_RETRIES = 3
_RECONNECT_BASE_DELAY = 1.0  # seconds, doubled each retry
_RESULT_SUMMARY_MAX = 500  # chars to keep in audit log


# ---------------------------------------------------------------------------
# Internal session wrapper — tracks connection state alongside the session
# ---------------------------------------------------------------------------


@dataclass
class _ManagedSession:
    """Wraps an MCP ClientSession with lifecycle metadata."""

    connection_id: str
    config: ConnectionConfig
    credentials: str | None = None

    # The live MCP session (None when disconnected)
    session: Any = None

    # Context managers that must be kept alive for the session's duration.
    # stdio: (stdio_client_cm, client_session_cm)
    # sse/http: (transport_cm, client_session_cm)
    _transport_cm: Any = None
    _session_cm: Any = None

    connected: bool = False
    last_ping: float = 0.0
    consecutive_failures: int = 0


# ---------------------------------------------------------------------------
# Database pool (shared with registry — injected at startup)
# ---------------------------------------------------------------------------

_db_pool: asyncpg.Pool | None = None


def set_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool  # noqa: PLW0603
    _db_pool = pool


def _get_pool() -> asyncpg.Pool:
    assert _db_pool is not None, "ClientManager DB pool not initialised"
    return _db_pool


# ---------------------------------------------------------------------------
# MCPClientManager
# ---------------------------------------------------------------------------


class MCPClientManager:
    """Manages active MCP client sessions for a worker process."""

    def __init__(self, registry: ConnectionRegistry) -> None:
        self.registry = registry
        self._sessions: dict[str, _ManagedSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._health_task: asyncio.Task | None = None

    # ── Lifecycle ───────────────────────────────────────────

    def start_health_checks(self) -> None:
        """Start the background health-check loop."""
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())
            log.info("health check loop started")

    async def shutdown(self) -> None:
        """Disconnect all sessions and stop health checks."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._health_task

        for conn_id in list(self._sessions):
            await self.disconnect(conn_id)

        log.info("client manager shut down", session_count=0)

    # ── Get / ensure session ────────────────────────────────

    async def get_session(self, connection_id: str):
        """Get or create an MCP ClientSession for the given connection."""
        lock = self._locks.setdefault(connection_id, asyncio.Lock())
        async with lock:
            ms = self._sessions.get(connection_id)
            if ms and ms.connected and ms.session:
                return ms.session

            # (Re-)connect
            await self._connect(connection_id)
            return self._sessions[connection_id].session

    # ── Call tool ───────────────────────────────────────────

    async def call_tool(
        self,
        connection_id: str,
        tool_name: str,
        arguments: dict,
        *,
        org_id: str | None = None,
        agent_role: str | None = None,
        pipeline_id: str | None = None,
    ) -> dict:
        """Call a tool on an MCP server.

        Handles reconnection on failure and logs the call to the audit table.
        Returns ``{"content": [...], "is_error": bool}``.
        """
        t0 = time.monotonic()
        success = False
        result_summary = ""
        error_msg: str | None = None

        try:
            result = await self._call_with_retry(connection_id, tool_name, arguments)
            success = not result.get("is_error", False)
            result_summary = _summarize_result(result)
            return result

        except Exception as exc:
            error_msg = str(exc)
            raise

        finally:
            duration_ms = int((time.monotonic() - t0) * 1000)
            # Fire-and-forget audit log
            asyncio.create_task(
                self._log_tool_call(
                    org_id=org_id,
                    connection_id=connection_id,
                    pipeline_id=pipeline_id,
                    agent_role=agent_role,
                    tool_name=tool_name,
                    arguments=arguments,
                    result_summary=result_summary,
                    success=success,
                    duration_ms=duration_ms,
                    error_message=error_msg,
                )
            )

    async def _call_with_retry(
        self,
        connection_id: str,
        tool_name: str,
        arguments: dict,
    ) -> dict:
        """Attempt a tool call, reconnecting up to once on transport failure."""
        last_exc: Exception | None = None

        for attempt in range(2):  # first try + one reconnect
            try:
                session = await self.get_session(connection_id)
                result = await session.call_tool(tool_name, arguments)
                # Reset failure counter on success
                ms = self._sessions.get(connection_id)
                if ms:
                    ms.consecutive_failures = 0

                return {
                    "content": [
                        {
                            "type": getattr(block, "type", "text"),
                            "text": getattr(block, "text", str(block)),
                        }
                        for block in result.content
                    ],
                    "is_error": result.isError if hasattr(result, "isError") else False,
                }

            except Exception as exc:
                last_exc = exc
                log.warning(
                    "tool call failed, will reconnect",
                    connection_id=connection_id,
                    tool_name=tool_name,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                # Force reconnect on next get_session
                await self.disconnect(connection_id)

        raise RuntimeError(
            f"Tool call {tool_name} failed after reconnect: {last_exc}"
        ) from last_exc

    # ── List tools ──────────────────────────────────────────

    async def list_tools(self, connection_id: str) -> list[dict]:
        """List all tools available on an MCP server."""
        session = await self.get_session(connection_id)
        result = await session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            }
            for tool in result.tools
        ]

    # ── Disconnect ──────────────────────────────────────────

    async def disconnect(self, connection_id: str) -> None:
        """Disconnect and clean up a single session."""
        ms = self._sessions.pop(connection_id, None)
        if ms is None:
            return

        log.info("disconnecting MCP session", connection_id=connection_id)

        # Tear down in reverse order: session first, then transport
        if ms._session_cm:
            with suppress(Exception):
                await ms._session_cm.__aexit__(None, None, None)

        if ms._transport_cm:
            with suppress(Exception):
                await ms._transport_cm.__aexit__(None, None, None)

    # ── Connection status ───────────────────────────────────

    def get_status(self) -> dict[str, dict]:
        """Return status info for all managed sessions."""
        return {
            conn_id: {
                "connected": ms.connected,
                "service": ms.config.service.value,
                "display_name": ms.config.display_name,
                "consecutive_failures": ms.consecutive_failures,
                "last_ping": ms.last_ping,
            }
            for conn_id, ms in self._sessions.items()
        }

    # ── Internal: connect ───────────────────────────────────

    async def _connect(self, connection_id: str) -> None:
        """Establish an MCP session with retries and exponential backoff."""
        config = await self.registry.get_connection(connection_id)
        credentials = await self.registry._resolve_credentials(config)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RECONNECT_RETRIES):
            try:
                ms = await self._open_session(connection_id, config, credentials)
                self._sessions[connection_id] = ms

                log.info(
                    "MCP session connected",
                    connection_id=connection_id,
                    service=config.service.value,
                    transport=config.transport.value,
                    attempt=attempt + 1,
                )
                return

            except Exception as exc:
                last_exc = exc
                delay = _RECONNECT_BASE_DELAY * (2 ** attempt)
                log.warning(
                    "MCP connect failed, retrying",
                    connection_id=connection_id,
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"Failed to connect to {config.display_name} after "
            f"{_MAX_RECONNECT_RETRIES} attempts: {last_exc}"
        ) from last_exc

    async def _open_session(
        self,
        connection_id: str,
        config: ConnectionConfig,
        credentials: str | None,
    ) -> _ManagedSession:
        """Open the transport and initialise the MCP ClientSession."""
        import os
        from mcp import ClientSession

        ms = _ManagedSession(
            connection_id=connection_id,
            config=config,
            credentials=credentials,
        )

        if config.transport == TransportType.STDIO:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            if not config.command:
                raise ValueError(f"stdio transport requires 'command' for {config.display_name}")

            env = {**os.environ, **(config.env or {})}
            if credentials:
                from connections.client import _credential_env_key
                env[_credential_env_key(config)] = credentials

            params = StdioServerParameters(
                command=config.command,
                args=config.args or [],
                env=env,
            )
            transport_cm = stdio_client(params)
            read_stream, write_stream = await transport_cm.__aenter__()

        elif config.transport == TransportType.SSE:
            from mcp.client.sse import sse_client

            if not config.server_url:
                raise ValueError(f"SSE transport requires 'server_url' for {config.display_name}")

            headers: dict[str, str] = {}
            if credentials:
                headers["Authorization"] = f"Bearer {credentials}"

            transport_cm = sse_client(config.server_url, headers=headers)
            read_stream, write_stream = await transport_cm.__aenter__()

        elif config.transport == TransportType.STREAMABLE_HTTP:
            from mcp.client.streamable_http import streamablehttp_client

            if not config.server_url:
                raise ValueError(
                    f"Streamable HTTP requires 'server_url' for {config.display_name}"
                )

            headers = {}
            if credentials:
                headers["Authorization"] = f"Bearer {credentials}"

            transport_cm = streamablehttp_client(config.server_url, headers=headers)
            result = await transport_cm.__aenter__()
            read_stream, write_stream = result[0], result[1]

        else:
            raise ValueError(f"Unsupported transport: {config.transport}")

        ms._transport_cm = transport_cm

        session_cm = ClientSession(read_stream, write_stream)
        session = await session_cm.__aenter__()
        await session.initialize()

        ms._session_cm = session_cm
        ms.session = session
        ms.connected = True
        ms.last_ping = time.monotonic()
        ms.consecutive_failures = 0

        return ms

    # ── Internal: health loop ───────────────────────────────

    async def _health_loop(self) -> None:
        """Periodically ping active sessions and reconnect dead ones."""
        while True:
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

            for conn_id in list(self._sessions):
                ms = self._sessions.get(conn_id)
                if not ms or not ms.connected:
                    continue

                try:
                    # Ping by listing tools (lightweight MCP operation)
                    await asyncio.wait_for(
                        ms.session.list_tools(),
                        timeout=10.0,
                    )
                    ms.last_ping = time.monotonic()
                    ms.consecutive_failures = 0

                except Exception as exc:
                    ms.consecutive_failures += 1
                    log.warning(
                        "health check failed",
                        connection_id=conn_id,
                        service=ms.config.service.value,
                        failures=ms.consecutive_failures,
                        error=str(exc),
                    )

                    if ms.consecutive_failures >= _MAX_RECONNECT_RETRIES:
                        log.error(
                            "connection dead, disconnecting",
                            connection_id=conn_id,
                            service=ms.config.service.value,
                        )
                        await self.disconnect(conn_id)
                    else:
                        # Attempt reconnect
                        try:
                            await self.disconnect(conn_id)
                            await self._connect(conn_id)
                            log.info(
                                "reconnected after health failure",
                                connection_id=conn_id,
                            )
                        except Exception as reconn_exc:
                            log.error(
                                "reconnect failed",
                                connection_id=conn_id,
                                error=str(reconn_exc),
                            )

    # ── Internal: audit logging ─────────────────────────────

    async def _log_tool_call(
        self,
        *,
        org_id: str | None,
        connection_id: str,
        pipeline_id: str | None,
        agent_role: str | None,
        tool_name: str,
        arguments: dict,
        result_summary: str,
        success: bool,
        duration_ms: int,
        error_message: str | None,
    ) -> None:
        """Insert a row into connection_tool_calls for audit / cost tracking."""
        if not org_id:
            # Try to get org_id from the connection config
            ms = self._sessions.get(connection_id)
            if ms:
                org_id = ms.config.org_id

        if not org_id:
            log.warning("cannot log tool call without org_id", connection_id=connection_id)
            return

        try:
            pool = _get_pool()
            await pool.execute(
                """
                INSERT INTO connection_tool_calls (
                    org_id, connection_id, pipeline_id, agent_role,
                    tool_name, arguments, result_summary,
                    success, duration_ms, error_message
                ) VALUES (
                    $1, $2::uuid, $3, $4,
                    $5, $6::jsonb, $7,
                    $8, $9, $10
                )
                """,
                org_id,
                connection_id,
                pipeline_id,
                agent_role,
                tool_name,
                json.dumps(arguments) if arguments else "{}",
                result_summary[:_RESULT_SUMMARY_MAX] if result_summary else None,
                success,
                duration_ms,
                error_message,
            )
        except Exception as exc:
            # Audit logging should never break the tool call flow
            log.error("failed to log tool call", error=str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_result(result: dict) -> str:
    """Extract a short text summary from a tool call result."""
    content = result.get("content", [])
    parts: list[str] = []
    for block in content:
        text = block.get("text", "")
        if text:
            parts.append(text)
    summary = "\n".join(parts)
    if len(summary) > _RESULT_SUMMARY_MAX:
        return summary[:_RESULT_SUMMARY_MAX - 3] + "..."
    return summary
