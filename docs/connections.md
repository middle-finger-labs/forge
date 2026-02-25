# MCP Connections System

The connections system integrates external services (Notion, Linear, Figma, Jira, Google Drive) into Forge pipelines via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). Each connected service becomes a set of tools that agents can use during pipeline execution.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│  Pipeline Agents (BA, PM, Engineer, QA, etc.)            │
│  Each agent sees only tools matching its permission level│
└────────────────────┬─────────────────────────────────────┘
                     │ filtered tool list
┌────────────────────▼─────────────────────────────────────┐
│  AgentConnectionTools                                     │
│  Assembles tools from all connections, namespaces them,   │
│  logs usage to pipeline conversation                      │
└────────────────────┬─────────────────────────────────────┘
                     │ call_tool()
┌────────────────────▼─────────────────────────────────────┐
│  MCPClientManager                                         │
│  Manages MCP sessions, retries, health checks, auditing   │
└────────────────────┬─────────────────────────────────────┘
                     │ stdio / SSE / HTTP
┌────────────────────▼─────────────────────────────────────┐
│  MCP Servers (Notion, Linear, Figma, Jira, Google Drive)  │
└──────────────────────────────────────────────────────────┘
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `connections/models.py` | Data models: `ConnectionConfig`, `ToolPermission`, `ServiceType`, `PermissionLevel` |
| `connections/registry.py` | CRUD operations for connections (PostgreSQL backed) |
| `connections/client_manager.py` | MCP session lifecycle, tool calls, health checks |
| `connections/client.py` | Transport-specific session factories (stdio, SSE, HTTP) |
| `connections/tool_filter.py` | Permission-based tool filtering and classification |
| `connections/agent_tools.py` | Bridge between agents and MCP tools with logging |
| `connections/pipeline_hooks.py` | Automatic actions at pipeline lifecycle events |
| `connections/oauth.py` | OAuth authorization code flow for supported services |
| `api/routes/connections.py` | REST API endpoints for connection management |

## Supported Services

| Service | Transport | Auth | Default Use |
|---------|-----------|------|-------------|
| Notion | Streamable HTTP | OAuth | Specs, docs, project pages |
| Linear | SSE | OAuth | Issue tracking, ticket management |
| Figma | Streamable HTTP | OAuth | Design references (read-only) |
| Jira | stdio | API token | Issue tracking (alternative to Linear) |
| Google Drive | stdio | OAuth | Document search and reference |

## How It Works

### 1. Connection Setup

Users connect services through the Settings > Connections UI:
- Select a service from available presets
- Authenticate via OAuth or API token
- Test the connection (discovers available tools)
- Configure permissions per agent role

### 2. Tool Injection

When a pipeline runs, the `AgentConnectionTools` class:
1. Fetches all enabled connections for the org
2. Filters tools based on the agent's permission level
3. Namespaces tools (e.g., `notion_search`, `linear_create_issue`)
4. Injects tool definitions into the agent's system prompt
5. Handles tool call execution and logging

### 3. Permission Filtering

Tools are classified as `read`, `write`, or `admin` based on their names:
- **Read**: `search`, `get`, `list`, `fetch`, `query`, `find`
- **Write**: `create`, `update`, `add`, `edit`, `send`
- **Admin**: `delete`, `remove`, `archive`, `destroy`

Permission levels control which classifications an agent can access:
- `NONE` — no tools
- `READ` — read tools only
- `WRITE` — read + write tools
- `FULL` — all tools including admin

### 4. Pipeline Hooks

Automatic actions triggered at pipeline lifecycle events:
- **Pipeline start**: Search Notion and Linear for related context
- **BA complete**: Create Notion spec page
- **PM complete**: Create Linear/Jira tickets
- **QA complete**: Create bug tickets for critical findings
- **Pipeline complete**: Mark tickets as Done, update Notion
- **Pipeline failure**: Create failure ticket, update Notion to Blocked

All hooks are best-effort (failures never block the pipeline) and configurable per connection.

### 5. Audit Logging

Every MCP tool call is logged to the `connection_tool_calls` table with:
- Connection and service info
- Pipeline and agent context
- Tool name and arguments
- Result summary, success status, duration
- Timestamp

## Database Schema

### `mcp_connections` table
Stores connection configuration, credentials (encrypted), discovered tools, and permission settings.

### `connection_tool_calls` table
Audit log of every tool invocation through the client manager.

See `infrastructure/migrations/012_mcp_connections.sql` and `013_connection_tool_calls.sql`.

## API Endpoints

See `api/routes/connections.py` for the full REST API. Key endpoints:

- `GET /api/connections` — list all connections
- `POST /api/connections` — create a connection
- `POST /api/connections/{id}/test` — test connectivity
- `PUT /api/connections/{id}/permissions` — update permission config
- `PUT /api/connections/{id}/automation` — update automation flags
- `GET /api/connections/activity/{pipeline_id}` — tool call audit log

## Related Documentation

- [Connection Setup Guide](connections-setup.md) — step-by-step for each service
- [Permissions Guide](connections-permissions.md) — how the permission system works
- [Development Guide](connections-development.md) — how to add a new MCP service
