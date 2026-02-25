# Adding a New MCP Service

This guide walks through adding support for a new MCP service to the Forge connections system.

## Prerequisites

You need:
- An MCP server for the service (existing package or custom implementation)
- The server's transport type (stdio, SSE, or streamable HTTP)
- Authentication method (OAuth or API token)

## Step 1: Add the Service to Models

Edit `connections/models.py`:

### Add to ServiceType enum

```python
class ServiceType(str, Enum):
    NOTION = "notion"
    LINEAR = "linear"
    FIGMA = "figma"
    JIRA = "jira"
    GOOGLE_DRIVE = "google_drive"
    YOUR_SERVICE = "your_service"  # <-- add this
```

### Add a service preset

```python
SERVICE_PRESETS[ServiceType.YOUR_SERVICE] = {
    "transport": TransportType.SSE,            # or STDIO, STREAMABLE_HTTP
    "server_url": "https://mcp.service.com",   # for SSE/HTTP transports
    # "command": "npx",                        # for stdio transports
    # "args": ["-y", "mcp-server-package"],    # for stdio transports
    "auth_type": "oauth",                      # or "token"
    "default_permission": "read",
    "agent_permissions": {
        "business_analyst": "read",
        "researcher": "read",
        "architect": "read",
        "pm": "write",
        "engineer": "read",
        "qa": "read",
        "cto": "read",
    },
}
```

### Add OAuth config (if using OAuth)

```python
OAUTH_CONFIGS[ServiceType.YOUR_SERVICE] = {
    "authorize_url": "https://service.com/oauth/authorize",
    "token_url": "https://service.com/oauth/token",
    "scopes": ["read", "write"],
    "env_client_id": "OAUTH_YOUR_SERVICE_CLIENT_ID",
    "env_client_secret": "OAUTH_YOUR_SERVICE_CLIENT_SECRET",
    "token_auth": "post_body",  # or "basic"
    "setup_instructions": "How to get credentials for this service.",
}
```

## Step 2: Add Transport Support

If your MCP server uses a standard transport (stdio, SSE, or streamable HTTP), it should work automatically through `connections/client.py`.

For custom transport needs, add a new case to `create_mcp_session()` in `connections/client.py`:

```python
@asynccontextmanager
async def create_mcp_session(config, credentials=None):
    if config.transport == TransportType.YOUR_CUSTOM:
        async with _your_custom_session(config, credentials) as session:
            yield session
    # ... existing transports
```

## Step 3: Add Credential Mapping

In `connections/client.py`, update `_credential_env_key()` to map your service to the environment variable expected by the MCP server:

```python
def _credential_env_key(config):
    return {
        ServiceType.NOTION: "NOTION_API_KEY",
        ServiceType.LINEAR: "LINEAR_API_KEY",
        # ...
        ServiceType.YOUR_SERVICE: "YOUR_SERVICE_API_KEY",
    }.get(config.service, "MCP_API_KEY")
```

## Step 4: Update the Desktop UI

### Add service info

In `desktop/src/types/connection.ts`, add your service to `SERVICE_INFO`:

```typescript
export const SERVICE_INFO: Record<ServiceType, { emoji: string; displayName: string }> = {
  // ...existing services
  your_service: { emoji: "🔧", displayName: "Your Service" },
};
```

Also add `"your_service"` to the `ServiceType` union type.

### Add icon to agent_tools

In `connections/agent_tools.py`, add to `_SERVICE_ICONS`:

```python
_SERVICE_ICONS = {
    # ...existing services
    "your_service": "\U0001f527",  # 🔧
}
```

## Step 5: Update Agent Prompts

In each agent's system prompt file (`agents/stage_*.py`), add guidance for using the new service in the "Connected Services" section:

```python
# In the SYSTEM_PROMPT string:
# - **Check Your Service** for relevant data when implementing features.
```

Only add guidance to agents where the service is relevant.

## Step 6: Add Pipeline Hook Support (Optional)

If the service should participate in automatic pipeline actions, update `connections/pipeline_hooks.py`:

```python
async def on_pipeline_start(self, pipeline_id, org_id, spec):
    # ...existing code

    # Search Your Service for related data
    your_conns = await self._get_connections(org_id, "your_service")
    for conn in your_conns:
        if not self._get_automation(conn, "auto_search_context"):
            continue
        result = await self._call_tool_safe(
            conn.id, "search", {"query": spec[:200]},
            org_id=org_id, pipeline_id=pipeline_id,
        )
        # ...process result
```

## Step 7: Add Setup Guide

If the service uses token auth, add credential field definitions to the setup guide endpoint in `api/routes/connections.py`:

```python
# In the get_setup_guide() function, add fields for your service:
if service_type == ServiceType.YOUR_SERVICE:
    fields = [
        {
            "field": "api_key",
            "label": "API Key",
            "placeholder": "sk-...",
            "help": "Generate at service.com/settings/api",
        },
    ]
```

## Step 8: Add Database Migration

Create a new migration file if you need service-specific schema changes. The base `mcp_connections` and `connection_tool_calls` tables handle all services generically.

## Step 9: Write Tests

Add tests to `tests/test_connections.py`:

```python
class TestYourServiceIntegration:
    def test_tool_classification(self):
        f = ToolFilter()
        assert f.classify_tool("your_service_search", "") == "read"
        assert f.classify_tool("your_service_create", "") == "write"

    async def test_permission_filtering(self):
        config = _make_config(
            service=ServiceType.YOUR_SERVICE,
            default_permission=PermissionLevel.READ,
        )
        # ...test that filtering works correctly
```

## Step 10: Environment Variables

Document the required environment variables:

```bash
# For OAuth services:
OAUTH_YOUR_SERVICE_CLIENT_ID=...
OAUTH_YOUR_SERVICE_CLIENT_SECRET=...

# For token-based services:
# (tokens are stored encrypted in the database, no env vars needed)
```

## Checklist

- [ ] `ServiceType` enum updated
- [ ] `SERVICE_PRESETS` entry added
- [ ] `OAUTH_CONFIGS` entry added (if OAuth)
- [ ] `_credential_env_key()` mapping added
- [ ] `SERVICE_INFO` in TypeScript updated
- [ ] `_SERVICE_ICONS` in agent_tools updated
- [ ] Agent prompts updated with service guidance
- [ ] Pipeline hooks updated (if applicable)
- [ ] Setup guide endpoint configured
- [ ] Tests written
- [ ] Environment variables documented
