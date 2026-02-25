"""MCP connection registry — manages lifecycle of external MCP server connections.

Handles CRUD, credential storage (via org_secrets), connection testing, and
tool discovery for each registered MCP server.

Usage::

    from connections.registry import ConnectionRegistry

    registry = ConnectionRegistry()
    await registry.initialize(db_pool)

    connections = await registry.list_connections("org-123")
    result = await registry.test_connection("conn-uuid")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg
import structlog

from auth.secrets import encrypt_secret, decrypt_secret
from connections.models import (
    ConnectionConfig,
    DiscoveredTool,
    PermissionLevel,
    ServiceType,
    ToolPermission,
    TransportType,
)

log = structlog.get_logger().bind(component="connections.registry")

# ---------------------------------------------------------------------------
# Database pool management (same pattern as auth.secrets)
# ---------------------------------------------------------------------------

_db_pool: asyncpg.Pool | None = None


def set_db_pool(pool: asyncpg.Pool) -> None:
    """Inject the shared database pool (called during app startup)."""
    global _db_pool  # noqa: PLW0603
    _db_pool = pool


def _get_pool() -> asyncpg.Pool:
    assert _db_pool is not None, "Connections DB pool not initialised — call set_db_pool() first"
    return _db_pool


# ---------------------------------------------------------------------------
# Row ↔ ConnectionConfig mapping
# ---------------------------------------------------------------------------


def _row_to_config(row: asyncpg.Record) -> ConnectionConfig:
    """Convert a database row to a ConnectionConfig dataclass."""
    agent_perms_raw = row["agent_permissions"] or {}
    if isinstance(agent_perms_raw, str):
        agent_perms_raw = json.loads(agent_perms_raw)
    agent_perms = {
        k: PermissionLevel(v) for k, v in agent_perms_raw.items()
    }

    tool_perms_raw = row["tool_permissions"] or []
    if isinstance(tool_perms_raw, str):
        tool_perms_raw = json.loads(tool_perms_raw)
    tool_perms = [
        ToolPermission(
            tool_name=tp["tool_name"],
            allowed=tp.get("allowed", True),
            allowed_agents=tp.get("allowed_agents"),
        )
        for tp in tool_perms_raw
    ]

    discovered_raw = row["discovered_tools"] or []
    if isinstance(discovered_raw, str):
        discovered_raw = json.loads(discovered_raw)

    return ConnectionConfig(
        id=str(row["id"]),
        org_id=row["org_id"],
        service=ServiceType(row["service"]),
        display_name=row["display_name"],
        transport=TransportType(row["transport"]),
        server_url=row["server_url"],
        command=row["command"],
        args=list(row["args"] or []),
        env=row.get("env") or {},
        auth_type=row["auth_type"],
        credential_secret_key=row["credential_secret_key"],
        default_permission=PermissionLevel(row["default_permission"]),
        agent_permissions=agent_perms,
        tool_permissions=tool_perms,
        enabled=row["enabled"],
        last_connected_at=(
            row["last_connected_at"].isoformat() if row["last_connected_at"] else None
        ),
        discovered_tools=discovered_raw,
        created_at=row["created_at"].isoformat() if row["created_at"] else None,
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
    )


# ---------------------------------------------------------------------------
# ConnectionRegistry
# ---------------------------------------------------------------------------


class ConnectionRegistry:
    """Manages all MCP connections for an organisation."""

    # ── List / Get ──────────────────────────────────────────

    async def list_connections(self, org_id: str) -> list[ConnectionConfig]:
        """List all connections for an org, ordered by display_name."""
        pool = _get_pool()
        rows = await pool.fetch(
            """
            SELECT * FROM mcp_connections
            WHERE org_id = $1
            ORDER BY display_name
            """,
            org_id,
        )
        return [_row_to_config(r) for r in rows]

    async def get_connection(self, connection_id: str) -> ConnectionConfig:
        """Get a specific connection by ID.

        Raises ``KeyError`` if not found.
        """
        pool = _get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM mcp_connections WHERE id = $1::uuid",
            connection_id,
        )
        if row is None:
            raise KeyError(f"Connection {connection_id} not found")
        return _row_to_config(row)

    # ── Create ──────────────────────────────────────────────

    async def create_connection(
        self,
        org_id: str,
        *,
        service: ServiceType,
        display_name: str,
        transport: TransportType,
        server_url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        auth_type: str = "token",
        credentials: str | None = None,
        default_permission: PermissionLevel = PermissionLevel.READ,
        agent_permissions: dict[str, str] | None = None,
    ) -> ConnectionConfig:
        """Register a new MCP connection.

        If *credentials* is provided, it is encrypted and stored in
        ``org_secrets`` under a deterministic key.
        """
        pool = _get_pool()

        # Store credentials in org_secrets if provided
        credential_secret_key: str | None = None
        if credentials:
            credential_secret_key = f"mcp_{service.value}_{display_name.lower().replace(' ', '_')}"
            encrypted = encrypt_secret(credentials)
            await pool.execute(
                """
                INSERT INTO org_secrets (org_id, key, encrypted_value, created_by, updated_at)
                VALUES ($1, $2, $3, 'system', NOW())
                ON CONFLICT (org_id, key)
                DO UPDATE SET encrypted_value = EXCLUDED.encrypted_value, updated_at = NOW()
                """,
                org_id,
                credential_secret_key,
                encrypted,
            )

        agent_perms_json = json.dumps(agent_permissions or {})

        row = await pool.fetchrow(
            """
            INSERT INTO mcp_connections (
                org_id, service, display_name, transport,
                server_url, command, args, env,
                auth_type, credential_secret_key,
                default_permission, agent_permissions
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10,
                $11, $12::jsonb
            )
            RETURNING *
            """,
            org_id,
            service.value,
            display_name,
            transport.value,
            server_url,
            command,
            args or [],
            json.dumps(env or {}),
            auth_type,
            credential_secret_key,
            default_permission.value,
            agent_perms_json,
        )

        config = _row_to_config(row)
        log.info(
            "connection created",
            org_id=org_id,
            service=service.value,
            connection_id=config.id,
        )
        return config

    # ── Update ──────────────────────────────────────────────

    async def update_connection(
        self,
        connection_id: str,
        *,
        display_name: str | None = None,
        server_url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        credentials: str | None = None,
        default_permission: str | None = None,
        agent_permissions: dict[str, str] | None = None,
        tool_permissions: list[dict] | None = None,
        enabled: bool | None = None,
    ) -> ConnectionConfig:
        """Update an existing connection.  Only non-None fields are changed."""
        pool = _get_pool()

        # Fetch current config to get org_id for credential storage
        current = await self.get_connection(connection_id)

        # Update credentials if provided
        if credentials is not None:
            secret_key = current.credential_secret_key or (
                f"mcp_{current.service.value}_{current.display_name.lower().replace(' ', '_')}"
            )
            encrypted = encrypt_secret(credentials)
            await pool.execute(
                """
                INSERT INTO org_secrets (org_id, key, encrypted_value, created_by, updated_at)
                VALUES ($1, $2, $3, 'system', NOW())
                ON CONFLICT (org_id, key)
                DO UPDATE SET encrypted_value = EXCLUDED.encrypted_value, updated_at = NOW()
                """,
                current.org_id,
                secret_key,
                encrypted,
            )
            if not current.credential_secret_key:
                await pool.execute(
                    "UPDATE mcp_connections SET credential_secret_key = $1 WHERE id = $2::uuid",
                    secret_key,
                    connection_id,
                )

        # Build dynamic SET clause for non-None fields
        sets: list[str] = ["updated_at = NOW()"]
        params: list = []
        idx = 1

        for col, val in [
            ("display_name", display_name),
            ("server_url", server_url),
            ("command", command),
            ("default_permission", default_permission),
            ("enabled", enabled),
        ]:
            if val is not None:
                sets.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1

        if args is not None:
            sets.append(f"args = ${idx}")
            params.append(args)
            idx += 1

        if env is not None:
            sets.append(f"env = ${idx}::jsonb")
            params.append(json.dumps(env))
            idx += 1

        if agent_permissions is not None:
            sets.append(f"agent_permissions = ${idx}::jsonb")
            params.append(json.dumps(agent_permissions))
            idx += 1

        if tool_permissions is not None:
            sets.append(f"tool_permissions = ${idx}::jsonb")
            params.append(json.dumps(tool_permissions))
            idx += 1

        params.append(connection_id)
        where_idx = idx

        row = await pool.fetchrow(
            f"UPDATE mcp_connections SET {', '.join(sets)} WHERE id = ${where_idx}::uuid RETURNING *",
            *params,
        )
        if row is None:
            raise KeyError(f"Connection {connection_id} not found")

        log.info("connection updated", connection_id=connection_id)
        return _row_to_config(row)

    # ── Delete ──────────────────────────────────────────────

    async def delete_connection(self, connection_id: str) -> None:
        """Remove a connection and its stored credentials."""
        pool = _get_pool()

        row = await pool.fetchrow(
            "SELECT org_id, credential_secret_key FROM mcp_connections WHERE id = $1::uuid",
            connection_id,
        )
        if row is None:
            raise KeyError(f"Connection {connection_id} not found")

        # Delete the credential from org_secrets
        if row["credential_secret_key"]:
            await pool.execute(
                "DELETE FROM org_secrets WHERE org_id = $1 AND key = $2",
                row["org_id"],
                row["credential_secret_key"],
            )

        await pool.execute(
            "DELETE FROM mcp_connections WHERE id = $1::uuid",
            connection_id,
        )
        log.info(
            "connection deleted",
            connection_id=connection_id,
            org_id=row["org_id"],
        )

    # ── Test Connection ─────────────────────────────────────

    async def test_connection(self, connection_id: str) -> dict:
        """Test that a connection works.

        1. Resolve credentials from org_secrets
        2. Start an MCP client session
        3. Call list_tools()
        4. Return ``{"status": "ok", "tools": [...]}`` or
           ``{"status": "error", "message": "..."}``
        """
        try:
            config = await self.get_connection(connection_id)

            if not config.enabled:
                return {"status": "error", "message": "Connection is disabled"}

            # Resolve credentials
            creds = await self._resolve_credentials(config)

            # Connect and list tools
            tools = await self._connect_and_list_tools(config, creds)

            # Update last_connected_at and discovered_tools
            pool = _get_pool()
            await pool.execute(
                """
                UPDATE mcp_connections
                SET last_connected_at = NOW(),
                    discovered_tools = $1::jsonb,
                    updated_at = NOW()
                WHERE id = $2::uuid
                """,
                json.dumps(tools),
                connection_id,
            )

            log.info(
                "connection test passed",
                connection_id=connection_id,
                tool_count=len(tools),
            )
            return {
                "status": "ok",
                "tools": tools,
                "tool_count": len(tools),
            }

        except Exception as exc:
            log.error(
                "connection test failed",
                connection_id=connection_id,
                error=str(exc),
            )
            return {"status": "error", "message": str(exc)}

    # ── Discover Tools ──────────────────────────────────────

    async def discover_tools(self, connection_id: str) -> list[dict]:
        """Connect to the MCP server, call list_tools(), and cache the results.

        Returns tool name, description, and input schema for each tool.
        """
        result = await self.test_connection(connection_id)
        if result["status"] == "error":
            raise RuntimeError(result["message"])
        return result["tools"]

    # ── Get tools for agent ─────────────────────────────────

    async def get_tools_for_agent(
        self,
        org_id: str,
        agent_role: str,
    ) -> list[dict]:
        """Return all MCP tools available to a specific agent role.

        Filters by:
        1. Connection enabled
        2. Agent has sufficient permission on the connection
        3. Tool-level permissions allow this agent
        """
        connections = await self.list_connections(org_id)
        tools: list[dict] = []

        for conn in connections:
            if not conn.enabled:
                continue

            perm = conn.get_agent_permission(agent_role)
            if perm == PermissionLevel.NONE:
                continue

            # Build tool-level allow/deny map
            tool_overrides = {tp.tool_name: tp for tp in conn.tool_permissions}

            for tool in conn.discovered_tools:
                tool_name = tool.get("name", "")
                override = tool_overrides.get(tool_name)

                if override:
                    if not override.allowed:
                        continue
                    if (
                        override.allowed_agents is not None
                        and agent_role not in override.allowed_agents
                    ):
                        continue

                tools.append(
                    {
                        **tool,
                        "connection_id": conn.id,
                        "service": conn.service.value,
                        "permission": perm.value,
                    }
                )

        return tools

    # ── Internal helpers ────────────────────────────────────

    async def _resolve_credentials(self, config: ConnectionConfig) -> str | None:
        """Decrypt and return the credential for a connection."""
        if not config.credential_secret_key:
            return None

        pool = _get_pool()
        row = await pool.fetchrow(
            "SELECT encrypted_value FROM org_secrets WHERE org_id = $1 AND key = $2",
            config.org_id,
            config.credential_secret_key,
        )
        if row is None:
            return None

        return decrypt_secret(bytes(row["encrypted_value"]))

    async def _connect_and_list_tools(
        self,
        config: ConnectionConfig,
        credentials: str | None,
    ) -> list[dict]:
        """Start an MCP client, connect, and return discovered tools."""
        from connections.client import create_mcp_session

        tools: list[dict] = []
        async with create_mcp_session(config, credentials) as session:
            result = await session.list_tools()
            for tool in result.tools:
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                    }
                )

        return tools
