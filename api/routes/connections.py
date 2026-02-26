"""MCP connections API — manage external service integrations.

Endpoints:
    GET    /api/connections                          — list connections for the org
    POST   /api/connections                          — create a new connection
    GET    /api/connections/{id}                     — get a specific connection
    PUT    /api/connections/{id}                     — update a connection
    DELETE /api/connections/{id}                     — delete a connection
    POST   /api/connections/{id}/test                — test that a connection works
    POST   /api/connections/{id}/discover            — discover tools from the MCP server
    PUT    /api/connections/{id}/permissions          — update permission config
    PUT    /api/connections/{id}/automation           — update automation config
    GET    /api/connections/{id}/tools                — list tools with permission status
    GET    /api/connections/presets                   — list available service presets
    GET    /api/connections/tools/{agent}             — list all MCP tools available to an agent
    GET    /api/connections/activity/{pipeline_id}    — tool call audit log for a pipeline
    POST   /api/connections/oauth/start/{service}     — start OAuth flow
    GET    /api/connections/oauth/callback/{service}  — OAuth redirect handler
    GET    /api/connections/setup/{service}            — service-specific setup instructions
"""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from auth.middleware import get_current_user, require_org_member
from auth.types import ForgeUser
from connections.models import (
    OAUTH_CONFIGS,
    PermissionLevel,
    ServiceType,
    TransportType,
    SERVICE_PRESETS,
)

log = structlog.get_logger().bind(component="api.connections")

connections_router = APIRouter(prefix="/api/connections", tags=["connections"])

# ---------------------------------------------------------------------------
# Shared registry instance (lazy)
# ---------------------------------------------------------------------------

_registry = None


def _get_registry():
    global _registry  # noqa: PLW0603
    if _registry is None:
        from connections.registry import ConnectionRegistry

        _registry = ConnectionRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateConnectionRequest(BaseModel):
    service: str  # ServiceType value
    display_name: str
    transport: str | None = None  # auto-filled from preset if omitted
    server_url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    auth_type: str | None = None
    credentials: str | None = None  # plaintext — encrypted before storage
    default_permission: str | None = None  # auto-filled from preset if omitted
    agent_permissions: dict[str, str] | None = None  # auto-filled from preset


class UpdateConnectionRequest(BaseModel):
    display_name: str | None = None
    server_url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    credentials: str | None = None
    default_permission: str | None = None
    agent_permissions: dict[str, str] | None = None
    tool_permissions: list[dict] | None = None
    enabled: bool | None = None


class UpdatePermissionsRequest(BaseModel):
    default_permission: str | None = None
    agent_permissions: dict[str, str] | None = None
    tool_permissions: list[dict] | None = None


class UpdateAutomationRequest(BaseModel):
    automation_config: dict[str, bool]


class ToolCallResponse(BaseModel):
    id: str
    connection_id: str
    service: str = ""
    display_name: str = ""
    pipeline_id: str | None = None
    agent_role: str | None = None
    tool_name: str
    arguments: dict | None = None
    result_summary: str | None = None
    success: bool
    duration_ms: int | None = None
    error_message: str | None = None
    created_at: str


class OAuthStartRequest(BaseModel):
    connection_id: str | None = None  # if linking to an existing connection
    display_name: str | None = None   # for auto-creating connection after OAuth


class ConnectionResponse(BaseModel):
    id: str
    org_id: str
    service: str
    display_name: str
    transport: str
    server_url: str | None = None
    command: str | None = None
    args: list[str] = []
    auth_type: str = "token"
    has_credentials: bool = False
    default_permission: str = "read"
    agent_permissions: dict[str, str] = {}
    tool_permissions: list[dict] = []
    automation_config: dict = {}
    enabled: bool = True
    last_connected_at: str | None = None
    discovered_tools: list[dict] = []
    tool_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class TestConnectionResponse(BaseModel):
    status: str
    tools: list[dict] = []
    tool_count: int = 0
    message: str | None = None


class ServicePresetResponse(BaseModel):
    service: str
    display_name: str
    transport: str
    server_url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    auth_type: str
    default_permission: str = "read"
    agent_permissions: dict[str, str] = {}
    oauth_available: bool = False
    setup_instructions: str = ""


class ToolWithPermissionResponse(BaseModel):
    name: str
    description: str = ""
    input_schema: dict = {}
    classification: str = "read"  # read / write / admin
    allowed: bool = True
    allowed_agents: list[str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRIENDLY_NAMES = {
    ServiceType.NOTION: "Notion",
    ServiceType.LINEAR: "Linear",
    ServiceType.FIGMA: "Figma",
    ServiceType.JIRA: "Jira",
    ServiceType.GOOGLE_DRIVE: "Google Drive",
}


def _config_to_response(config) -> ConnectionResponse:
    """Convert a ConnectionConfig to an API response (never expose credentials)."""
    return ConnectionResponse(
        id=config.id,
        org_id=config.org_id,
        service=config.service.value,
        display_name=config.display_name,
        transport=config.transport.value,
        server_url=config.server_url,
        command=config.command,
        args=config.args,
        auth_type=config.auth_type,
        has_credentials=config.credential_secret_key is not None,
        default_permission=config.default_permission.value,
        agent_permissions={k: v.value for k, v in config.agent_permissions.items()},
        tool_permissions=[
            {"tool_name": tp.tool_name, "allowed": tp.allowed, "allowed_agents": tp.allowed_agents}
            for tp in config.tool_permissions
        ],
        automation_config=getattr(config, "automation_config", {}),
        enabled=config.enabled,
        last_connected_at=config.last_connected_at,
        discovered_tools=config.discovered_tools,
        tool_count=len(config.discovered_tools),
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


async def _verify_ownership(connection_id: str, user: ForgeUser):
    """Fetch a connection and verify the user's org owns it."""
    registry = _get_registry()
    try:
        config = await registry.get_connection(connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if config.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return config


# ---------------------------------------------------------------------------
# CRUD Endpoints — list and create (no path params, safe to register first)
# ---------------------------------------------------------------------------


@connections_router.get("", response_model=list[ConnectionResponse])
async def list_connections(user: ForgeUser = Depends(require_org_member)):
    """List all MCP connections for the org."""
    registry = _get_registry()
    configs = await registry.list_connections(user.org_id)
    return [_config_to_response(c) for c in configs]


@connections_router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(
    req: CreateConnectionRequest,
    user: ForgeUser = Depends(require_org_member),
):
    """Create a new MCP connection.

    If ``transport``, ``default_permission``, or ``agent_permissions`` are
    omitted, they are auto-filled from the service preset.
    """
    try:
        service = ServiceType(req.service)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown service: {req.service}. "
            f"Valid: {', '.join(s.value for s in ServiceType)}",
        )

    # Fill in defaults from preset if not specified
    preset = SERVICE_PRESETS.get(service, {})
    transport = TransportType(req.transport) if req.transport else preset.get("transport")
    if not transport:
        raise HTTPException(status_code=400, detail="transport is required")

    default_perm = req.default_permission or preset.get("default_permission", "read")
    agent_perms = req.agent_permissions
    if agent_perms is None:
        agent_perms = preset.get("agent_permissions")

    registry = _get_registry()
    try:
        config = await registry.create_connection(
            org_id=user.org_id,
            service=service,
            display_name=req.display_name,
            transport=transport,
            server_url=req.server_url or preset.get("server_url"),
            command=req.command or preset.get("command"),
            args=req.args or preset.get("args"),
            env=req.env,
            auth_type=req.auth_type or preset.get("auth_type", "token"),
            credentials=req.credentials,
            default_permission=PermissionLevel(default_perm),
            agent_permissions=agent_perms,
        )
    except Exception as exc:
        log.error("failed to create connection", error=str(exc), org_id=user.org_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return _config_to_response(config)


# ---------------------------------------------------------------------------
# Static paths — MUST be registered BEFORE /{connection_id} routes
# (FastAPI matches routes in registration order)
# ---------------------------------------------------------------------------


@connections_router.get("/presets", response_model=list[ServicePresetResponse])
async def list_presets(user: ForgeUser = Depends(require_org_member)):
    """List available service presets with default config and setup info."""
    presets = []
    for service, config in SERVICE_PRESETS.items():
        oauth_config = OAUTH_CONFIGS.get(service, {})
        # Check if OAuth client ID is configured
        oauth_available = False
        if oauth_config:
            client_id_env = oauth_config.get("env_client_id", "")
            oauth_available = bool(os.environ.get(client_id_env))

        presets.append(
            ServicePresetResponse(
                service=service.value,
                display_name=_FRIENDLY_NAMES.get(service, service.value),
                transport=config["transport"].value,
                server_url=config.get("server_url"),
                command=config.get("command"),
                args=config.get("args"),
                auth_type=config.get("auth_type", "token"),
                default_permission=config.get("default_permission", "read"),
                agent_permissions=config.get("agent_permissions", {}),
                oauth_available=oauth_available,
                setup_instructions=oauth_config.get("setup_instructions", ""),
            )
        )
    return presets


@connections_router.get("/tools/{agent_role}")
async def get_agent_tools(
    agent_role: str,
    user: ForgeUser = Depends(require_org_member),
):
    """List all MCP tools available to a specific agent role."""
    registry = _get_registry()
    tools = await registry.get_tools_for_agent(user.org_id, agent_role)
    return {"agent": agent_role, "tools": tools, "tool_count": len(tools)}


# ---------------------------------------------------------------------------
# Service Setup Guide
# ---------------------------------------------------------------------------


@connections_router.get("/setup/{service_name}")
async def get_setup_guide(
    service_name: str,
    user: ForgeUser = Depends(require_org_member),
):
    """Return service-specific setup instructions and configuration.

    Includes whether OAuth is available, what credentials are needed,
    and the default permission assignments.
    """
    try:
        service = ServiceType(service_name)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown service: {service_name}. "
            f"Valid: {', '.join(s.value for s in ServiceType)}",
        )

    preset = SERVICE_PRESETS.get(service, {})
    oauth_config = OAUTH_CONFIGS.get(service)

    oauth_available = False
    if oauth_config:
        client_id_env = oauth_config.get("env_client_id", "")
        oauth_available = bool(os.environ.get(client_id_env))

    guide: dict = {
        "service": service.value,
        "display_name": _FRIENDLY_NAMES.get(service, service.value),
        "auth_type": preset.get("auth_type", "token"),
        "transport": preset["transport"].value,
        "default_permission": preset.get("default_permission", "read"),
        "agent_permissions": preset.get("agent_permissions", {}),
        "oauth_available": oauth_available,
        "setup_instructions": "",
        "credential_fields": [],
    }

    if oauth_config:
        guide["setup_instructions"] = oauth_config.get("setup_instructions", "")

    # Service-specific credential field descriptions
    if service == ServiceType.NOTION:
        guide["credential_fields"] = [
            {
                "field": "token",
                "label": "Internal Integration Token",
                "placeholder": "ntn_...",
                "help": "Create at notion.so/profile/integrations",
            },
        ]
    elif service == ServiceType.LINEAR:
        guide["credential_fields"] = [
            {
                "field": "token",
                "label": "Personal API Key",
                "placeholder": "lin_api_...",
                "help": "Generate in Linear Settings > API",
            },
        ]
    elif service == ServiceType.FIGMA:
        guide["credential_fields"] = [
            {
                "field": "token",
                "label": "Personal Access Token",
                "placeholder": "figd_...",
                "help": "Generate in Figma Settings > Account > Personal access tokens",
            },
        ]
    elif service == ServiceType.JIRA:
        guide["credential_fields"] = [
            {
                "field": "url",
                "label": "Jira URL",
                "placeholder": "https://mycompany.atlassian.net",
                "help": "Your Atlassian site URL",
            },
            {
                "field": "email",
                "label": "Email",
                "placeholder": "you@company.com",
                "help": "Your Atlassian account email",
            },
            {
                "field": "token",
                "label": "API Token",
                "placeholder": "ATATT3x...",
                "help": "Generate at id.atlassian.com/manage-profile/security/api-tokens",
            },
        ]
    elif service == ServiceType.GOOGLE_DRIVE:
        guide["credential_fields"] = [
            {
                "field": "token",
                "label": "OAuth Token",
                "placeholder": "(set via OAuth flow)",
                "help": "Connect via OAuth to grant Drive read access",
            },
        ]

    return guide


# ---------------------------------------------------------------------------
# OAuth Flow
# ---------------------------------------------------------------------------


@connections_router.post("/oauth/start/{service_name}")
async def start_oauth(
    service_name: str,
    req: OAuthStartRequest | None = None,
    user: ForgeUser = Depends(require_org_member),
):
    """Start an OAuth authorization flow for a service.

    Returns ``{"authorize_url": "...", "state": "..."}`` — the frontend
    should redirect the user to ``authorize_url``.
    """
    try:
        service = ServiceType(service_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")

    if service not in OAUTH_CONFIGS:
        raise HTTPException(
            status_code=400,
            detail=f"{service_name} does not support OAuth. Use token-based auth.",
        )

    from connections.oauth import get_oauth_manager

    mgr = get_oauth_manager()

    # Build callback URL
    public_url = os.environ.get("FORGE_PUBLIC_URL", "http://localhost:8000")
    redirect_uri = f"{public_url}/api/connections/oauth/callback/{service_name}"

    try:
        result = await mgr.start_oauth(
            org_id=user.org_id,
            service=service,
            redirect_uri=redirect_uri,
            user_id=user.user_id,
            connection_id=req.connection_id if req else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


@connections_router.get("/oauth/callback/{service_name}")
async def oauth_callback(
    service_name: str,
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """OAuth redirect handler — exchanges auth code for tokens.

    This endpoint is called by the OAuth provider after the user authorizes.
    It does NOT require auth middleware since it's a redirect from an
    external service. The state token provides CSRF protection and carries
    the org_id context.

    On success, renders an HTML page that notifies the parent window and
    closes itself.
    """
    # Handle OAuth errors from the provider
    if error:
        detail = error_description or error
        log.warning("OAuth callback error", service=service_name, error=detail)
        return _oauth_result_page(
            success=False,
            service=service_name,
            message=f"Authorization denied: {detail}",
        )

    try:
        service = ServiceType(service_name)
    except ValueError:
        return _oauth_result_page(
            success=False,
            service=service_name,
            message=f"Unknown service: {service_name}",
        )

    from connections.oauth import get_oauth_manager

    mgr = get_oauth_manager()

    # Validate state token (also consumes it — one-time use)
    try:
        state_data = await mgr.validate_state(state)
    except ValueError:
        return _oauth_result_page(
            success=False,
            service=service_name,
            message="Invalid or expired authorization. Please try again.",
        )

    org_id = state_data["org_id"]
    connection_id = state_data.get("connection_id")

    # Build redirect URI (must match what was sent in the authorize request)
    public_url = os.environ.get("FORGE_PUBLIC_URL", "http://localhost:8000")
    redirect_uri = f"{public_url}/api/connections/oauth/callback/{service_name}"

    # Exchange code for tokens
    try:
        token_data = await mgr.exchange_oauth_code(service, code, redirect_uri)
    except Exception as exc:
        log.error("OAuth token exchange failed", service=service_name, error=str(exc))
        return _oauth_result_page(
            success=False,
            service=service_name,
            message=f"Failed to exchange authorization code: {str(exc)[:200]}",
        )

    # Store the tokens
    preset = SERVICE_PRESETS.get(service, {})
    display_name = _FRIENDLY_NAMES.get(service, service_name)

    try:
        secret_key = await mgr.store_oauth_tokens(
            org_id=org_id,
            service=service,
            token_data=token_data,
            connection_id=connection_id,
            display_name=display_name,
        )
    except Exception as exc:
        log.error("Failed to store OAuth tokens", service=service_name, error=str(exc))
        return _oauth_result_page(
            success=False,
            service=service_name,
            message="Failed to store credentials.",
        )

    # Create or update the connection record
    registry = _get_registry()
    try:
        if connection_id:
            # Update existing connection with new credentials
            await registry.update_connection(connection_id, credentials=None)
            # Manually set the credential_secret_key
            from connections.registry import _get_pool
            pool = _get_pool()
            await pool.execute(
                """
                UPDATE mcp_connections
                SET credential_secret_key = $1, updated_at = NOW()
                WHERE id = $2::uuid
                """,
                secret_key,
                connection_id,
            )
        else:
            # Create a new connection with the OAuth token
            default_perm = preset.get("default_permission", "read")
            agent_perms = preset.get("agent_permissions")

            # For OAuth services, the access token is the credential
            access_token = token_data.get("access_token", "")
            config = await registry.create_connection(
                org_id=org_id,
                service=service,
                display_name=display_name,
                transport=preset.get("transport", TransportType.STREAMABLE_HTTP),
                server_url=preset.get("server_url"),
                command=preset.get("command"),
                args=preset.get("args"),
                auth_type="oauth",
                credentials=access_token,
                default_permission=PermissionLevel(default_perm),
                agent_permissions=agent_perms,
            )
            connection_id = config.id
    except Exception as exc:
        log.error("Failed to create/update connection", service=service_name, error=str(exc))
        return _oauth_result_page(
            success=False,
            service=service_name,
            message="Connected to service but failed to save connection.",
        )

    log.info(
        "OAuth flow completed",
        service=service_name,
        org_id=org_id,
        connection_id=connection_id,
    )

    return _oauth_result_page(
        success=True,
        service=service_name,
        message=f"Successfully connected to {display_name}!",
        connection_id=connection_id,
    )


def _oauth_result_page(
    *,
    success: bool,
    service: str,
    message: str,
    connection_id: str | None = None,
) -> HTMLResponse:
    """Return an HTML page that posts the OAuth result back to the opener."""
    status = "success" if success else "error"
    icon = "&#x2705;" if success else "&#x274C;"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Forge - Connection {status}</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex;
           align-items: center; justify-content: center; height: 100vh;
           margin: 0; background: #0a0a0a; color: #e5e5e5; }}
    .card {{ text-align: center; padding: 2rem; max-width: 400px; }}
    .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    .msg  {{ font-size: 1.1rem; margin-bottom: 0.5rem; }}
    .sub  {{ color: #888; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <div class="msg">{message}</div>
    <div class="sub">You can close this window.</div>
  </div>
  <script>
    // Notify the parent window (dashboard) that OAuth is complete
    if (window.opener) {{
      window.opener.postMessage({{
        type: 'forge:oauth_complete',
        service: '{service}',
        status: '{status}',
        connectionId: '{connection_id or ""}',
        message: '{message.replace("'", "\\'")}'
      }}, '*');
      setTimeout(function() {{ window.close(); }}, 2000);
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Pipeline connection activity — static path, before parameterized routes
# ---------------------------------------------------------------------------


@connections_router.get(
    "/activity/{pipeline_id}",
    response_model=list[ToolCallResponse],
)
async def get_pipeline_activity(
    pipeline_id: str,
    user: ForgeUser = Depends(require_org_member),
):
    """Get all MCP tool calls for a pipeline, grouped by service."""
    import asyncpg

    from config.settings import get_settings

    settings = get_settings()
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL)
        try:
            rows = await conn.fetch(
                """
                SELECT tc.id, tc.connection_id, tc.pipeline_id,
                       tc.agent_role, tc.tool_name, tc.arguments,
                       tc.result_summary, tc.success, tc.duration_ms,
                       tc.error_message, tc.created_at,
                       mc.service, mc.display_name
                FROM connection_tool_calls tc
                LEFT JOIN mcp_connections mc ON mc.id = tc.connection_id
                WHERE tc.pipeline_id = $1 AND tc.org_id = $2
                ORDER BY tc.created_at ASC
                """,
                pipeline_id,
                user.org_id,
            )
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("failed to fetch pipeline activity", error=str(exc))
        return []

    return [
        ToolCallResponse(
            id=str(row["id"]),
            connection_id=str(row["connection_id"]),
            service=row["service"] or "",
            display_name=row["display_name"] or "",
            pipeline_id=row["pipeline_id"],
            agent_role=row["agent_role"],
            tool_name=row["tool_name"],
            arguments=dict(row["arguments"]) if row["arguments"] else None,
            result_summary=row["result_summary"],
            success=row["success"],
            duration_ms=row["duration_ms"],
            error_message=row["error_message"],
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Parameterized routes — /{connection_id} — MUST come AFTER static paths
# ---------------------------------------------------------------------------


@connections_router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: str,
    user: ForgeUser = Depends(require_org_member),
):
    """Get a specific MCP connection by ID."""
    config = await _verify_ownership(connection_id, user)
    return _config_to_response(config)


@connections_router.put("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: str,
    req: UpdateConnectionRequest,
    user: ForgeUser = Depends(require_org_member),
):
    """Update an existing MCP connection."""
    await _verify_ownership(connection_id, user)
    registry = _get_registry()

    update_kwargs: dict = {}
    if req.display_name is not None:
        update_kwargs["display_name"] = req.display_name
    if req.server_url is not None:
        update_kwargs["server_url"] = req.server_url
    if req.command is not None:
        update_kwargs["command"] = req.command
    if req.args is not None:
        update_kwargs["args"] = req.args
    if req.env is not None:
        update_kwargs["env"] = req.env
    if req.credentials is not None:
        update_kwargs["credentials"] = req.credentials
    if req.default_permission is not None:
        update_kwargs["default_permission"] = PermissionLevel(req.default_permission)
    if req.agent_permissions is not None:
        update_kwargs["agent_permissions"] = req.agent_permissions
    if req.tool_permissions is not None:
        update_kwargs["tool_permissions"] = req.tool_permissions
    if req.enabled is not None:
        update_kwargs["enabled"] = req.enabled

    try:
        config = await registry.update_connection(connection_id, **update_kwargs)
    except Exception as exc:
        log.error("failed to update connection", error=str(exc), connection_id=connection_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return _config_to_response(config)


@connections_router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    user: ForgeUser = Depends(require_org_member),
):
    """Delete an MCP connection."""
    await _verify_ownership(connection_id, user)
    registry = _get_registry()
    try:
        await registry.delete_connection(connection_id)
    except Exception as exc:
        log.error("failed to delete connection", error=str(exc), connection_id=connection_id)
        raise HTTPException(status_code=500, detail=str(exc))


@connections_router.post("/{connection_id}/test", response_model=TestConnectionResponse)
async def test_connection(
    connection_id: str,
    user: ForgeUser = Depends(require_org_member),
):
    """Test that a connection is working by attempting to list its tools."""
    config = await _verify_ownership(connection_id, user)

    from connections.client_manager import get_client_manager

    mgr = get_client_manager()
    try:
        tools = await mgr.list_tools(connection_id)
        return TestConnectionResponse(
            status="ok",
            tools=tools,
            tool_count=len(tools),
            message=f"Connected successfully. Found {len(tools)} tool(s).",
        )
    except BaseException as exc:
        log.warning(
            "connection test failed",
            connection_id=connection_id,
            service=config.service.value,
            error=str(exc),
        )
        return TestConnectionResponse(
            status="error",
            message=f"Connection failed: {str(exc)[:200]}",
        )


@connections_router.post("/{connection_id}/discover", response_model=ConnectionResponse)
async def discover_tools(
    connection_id: str,
    user: ForgeUser = Depends(require_org_member),
):
    """Discover tools from the MCP server and save them to the connection."""
    config = await _verify_ownership(connection_id, user)
    registry = _get_registry()

    from connections.client_manager import get_client_manager

    mgr = get_client_manager()
    try:
        tools = await mgr.list_tools(connection_id)
    except BaseException as exc:
        log.error("tool discovery failed", connection_id=connection_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to discover tools: {str(exc)[:200]}",
        )

    # Persist discovered tools
    try:
        config = await registry.update_connection(
            connection_id,
            discovered_tools=tools,
        )
    except Exception as exc:
        log.error("failed to save discovered tools", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return _config_to_response(config)


@connections_router.put("/{connection_id}/permissions", response_model=ConnectionResponse)
async def update_permissions(
    connection_id: str,
    req: UpdatePermissionsRequest,
    user: ForgeUser = Depends(require_org_member),
):
    """Update permission configuration for a connection.

    Allows updating default_permission, agent_permissions, and
    tool_permissions independently without touching other fields.
    """
    await _verify_ownership(connection_id, user)
    registry = _get_registry()

    update_kwargs: dict = {}
    if req.default_permission is not None:
        update_kwargs["default_permission"] = PermissionLevel(req.default_permission)
    if req.agent_permissions is not None:
        update_kwargs["agent_permissions"] = req.agent_permissions
    if req.tool_permissions is not None:
        update_kwargs["tool_permissions"] = req.tool_permissions

    if not update_kwargs:
        raise HTTPException(status_code=400, detail="No permission fields provided")

    try:
        config = await registry.update_connection(connection_id, **update_kwargs)
    except Exception as exc:
        log.error("failed to update permissions", error=str(exc), connection_id=connection_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return _config_to_response(config)


@connections_router.get(
    "/{connection_id}/tools",
    response_model=list[ToolWithPermissionResponse],
)
async def get_connection_tools(
    connection_id: str,
    agent_role: str | None = Query(None),
    user: ForgeUser = Depends(require_org_member),
):
    """List discovered tools for a connection with classification and permissions.

    Optionally filter by ``agent_role`` to show only tools that agent can use.
    """
    config = await _verify_ownership(connection_id, user)

    from connections.tool_filter import ToolFilter

    tool_filter = ToolFilter()
    results: list[ToolWithPermissionResponse] = []

    for tool in config.discovered_tools:
        name = tool.get("name", "")
        desc = tool.get("description", "")
        classification = tool_filter.classify_tool(name, desc)

        # Determine if this tool is allowed for the optional agent_role
        allowed = True
        if agent_role:
            from connections.models import PermissionLevel as PL

            agent_perm = config.get_agent_permission(agent_role)
            required = {"read": PL.READ, "write": PL.WRITE, "admin": PL.FULL}.get(
                classification, PL.READ
            )
            allowed = agent_perm.allows(required)

        # Check tool-level overrides
        allowed_agents = None
        for tp in config.tool_permissions:
            if tp.tool_name == name:
                if not tp.allowed:
                    allowed = False
                allowed_agents = tp.allowed_agents
                break

        results.append(
            ToolWithPermissionResponse(
                name=name,
                description=desc,
                input_schema=tool.get("input_schema", {}),
                classification=classification,
                allowed=allowed,
                allowed_agents=allowed_agents,
            )
        )

    return results


@connections_router.put("/{connection_id}/automation", response_model=ConnectionResponse)
async def update_automation(
    connection_id: str,
    req: UpdateAutomationRequest,
    user: ForgeUser = Depends(require_org_member),
):
    """Update automation configuration for a connection."""
    await _verify_ownership(connection_id, user)
    registry = _get_registry()

    try:
        config = await registry.update_connection(
            connection_id, automation_config=req.automation_config,
        )
    except Exception as exc:
        log.error("failed to update automation config", error=str(exc), connection_id=connection_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return _config_to_response(config)
