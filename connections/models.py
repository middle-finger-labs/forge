"""Data models for MCP connections.

These are plain dataclasses used throughout the connections module.
Pydantic models for the API layer live in ``api/routes/connections.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ServiceType(str, Enum):
    NOTION = "notion"
    LINEAR = "linear"
    FIGMA = "figma"
    JIRA = "jira"
    GOOGLE_DRIVE = "google_drive"


class TransportType(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class PermissionLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    FULL = "full"

    def allows(self, required: PermissionLevel) -> bool:
        """Check if this permission level satisfies *required*."""
        order = {
            PermissionLevel.NONE: 0,
            PermissionLevel.READ: 1,
            PermissionLevel.WRITE: 2,
            PermissionLevel.FULL: 3,
        }
        return order[self] >= order[required]


# ---------------------------------------------------------------------------
# Service presets — default config for each supported MCP server
# ---------------------------------------------------------------------------

SERVICE_PRESETS: dict[ServiceType, dict] = {
    ServiceType.NOTION: {
        "transport": TransportType.STREAMABLE_HTTP,
        "server_url": "https://mcp.notion.com/mcp",
        "auth_type": "oauth",
        "default_permission": "read",
        "agent_permissions": {
            "business_analyst": "write",
            "researcher": "read",
            "architect": "read",
            "pm": "write",
            "qa": "read",
            "cto": "read",
        },
    },
    ServiceType.LINEAR: {
        "transport": TransportType.SSE,
        "server_url": "https://mcp.linear.app/sse",
        "auth_type": "oauth",
        "default_permission": "read",
        "agent_permissions": {
            "business_analyst": "read",
            "researcher": "read",
            "architect": "read",
            "pm": "write",
            "qa": "write",
            "cto": "read",
        },
    },
    ServiceType.FIGMA: {
        "transport": TransportType.STREAMABLE_HTTP,
        "server_url": "https://mcp.figma.com/mcp",
        "auth_type": "oauth",
        "default_permission": "none",
        "agent_permissions": {
            "architect": "read",
            "engineer": "read",
        },
    },
    ServiceType.JIRA: {
        "transport": TransportType.STDIO,
        "command": "npx",
        "args": ["-y", "@aashari/mcp-server-atlassian-jira"],
        "auth_type": "token",
        "default_permission": "read",
        "agent_permissions": {
            "business_analyst": "read",
            "researcher": "read",
            "architect": "read",
            "pm": "write",
            "qa": "write",
            "cto": "read",
        },
    },
    ServiceType.GOOGLE_DRIVE: {
        "transport": TransportType.STDIO,
        "command": "npx",
        "args": ["-y", "@anthropics/mcp-server-gdrive"],
        "auth_type": "oauth",
        "default_permission": "read",
        "agent_permissions": {
            "business_analyst": "read",
            "researcher": "read",
            "architect": "read",
            "pm": "read",
            "qa": "read",
            "cto": "read",
        },
    },
}


# ---------------------------------------------------------------------------
# OAuth configuration per service
# ---------------------------------------------------------------------------

OAUTH_CONFIGS: dict[ServiceType, dict] = {
    ServiceType.NOTION: {
        "authorize_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": [],
        "env_client_id": "OAUTH_NOTION_CLIENT_ID",
        "env_client_secret": "OAUTH_NOTION_CLIENT_SECRET",
        "token_auth": "basic",  # Notion uses Basic auth for token exchange
        "setup_instructions": (
            "Create an internal integration at notion.so/profile/integrations, "
            "or use OAuth by registering a public integration."
        ),
    },
    ServiceType.LINEAR: {
        "authorize_url": "https://linear.app/oauth/authorize",
        "token_url": "https://api.linear.app/oauth/token",
        "scopes": ["read", "write", "issues:create"],
        "env_client_id": "OAUTH_LINEAR_CLIENT_ID",
        "env_client_secret": "OAUTH_LINEAR_CLIENT_SECRET",
        "token_auth": "post_body",
        "setup_instructions": (
            "Generate a personal API key in Linear Settings > API, "
            "or use OAuth by creating an application at linear.app/settings/api."
        ),
    },
    ServiceType.FIGMA: {
        "authorize_url": "https://www.figma.com/oauth",
        "token_url": "https://api.figma.com/v1/oauth/token",
        "scopes": ["files:read"],
        "env_client_id": "OAUTH_FIGMA_CLIENT_ID",
        "env_client_secret": "OAUTH_FIGMA_CLIENT_SECRET",
        "token_auth": "post_body",
        "setup_instructions": (
            "Register an app at figma.com/developers/apps, "
            "or generate a personal access token in Figma Settings."
        ),
    },
    ServiceType.GOOGLE_DRIVE: {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "env_client_id": "OAUTH_GOOGLE_CLIENT_ID",
        "env_client_secret": "OAUTH_GOOGLE_CLIENT_SECRET",
        "token_auth": "post_body",
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "setup_instructions": (
            "Create OAuth credentials in Google Cloud Console > APIs & Services > Credentials."
        ),
    },
    # Jira uses token auth only — no OAuth config needed
}


@dataclass
class ConnectionConfig:
    """Full configuration for an MCP connection."""

    id: str
    org_id: str
    service: ServiceType
    display_name: str
    transport: TransportType

    # Hosted MCP servers (SSE / Streamable HTTP)
    server_url: str | None = None

    # Self-hosted (stdio) servers
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # Auth
    auth_type: str = "token"
    credential_secret_key: str | None = None

    # Permissions
    default_permission: PermissionLevel = PermissionLevel.READ
    agent_permissions: dict[str, PermissionLevel] = field(default_factory=dict)
    tool_permissions: list[ToolPermission] = field(default_factory=list)

    # Automation
    automation_config: dict[str, bool] = field(default_factory=dict)

    # State
    enabled: bool = True
    last_connected_at: str | None = None
    discovered_tools: list[dict] = field(default_factory=list)

    created_at: str | None = None
    updated_at: str | None = None

    def get_agent_permission(self, agent_role: str) -> PermissionLevel:
        """Return the effective permission for an agent role."""
        if agent_role in self.agent_permissions:
            return self.agent_permissions[agent_role]
        return self.default_permission


@dataclass
class ToolPermission:
    """Fine-grained permission for a specific MCP tool."""

    tool_name: str
    allowed: bool = True
    allowed_agents: list[str] | None = None  # None = all agents with connection access


@dataclass
class DiscoveredTool:
    """A tool discovered from an MCP server via list_tools()."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
