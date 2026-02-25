# Connections Permission System

The permission system controls which MCP tools each pipeline agent can access. It operates at three levels with clear precedence rules.

## Permission Hierarchy

```
Tool-Level Override  (highest priority)
    ↓
Agent-Level Override
    ↓
Connection Default   (lowest priority)
```

### Level 1: Connection Default

Every connection has a `default_permission` that applies to all agents unless overridden:

| Level | Value | Access |
|-------|-------|--------|
| None | `none` | No tools — connection is invisible to this agent |
| Read | `read` | Read-classified tools only (search, get, list) |
| Write | `write` | Read + write tools (create, update, edit) |
| Full | `full` | All tools including admin (delete, archive) |

Example: A Notion connection with `default_permission: read` means all agents can search and read pages, but none can create or delete pages by default.

### Level 2: Agent-Level Override

Override the default for specific agent roles:

```json
{
  "default_permission": "read",
  "agent_permissions": {
    "business_analyst": "write",
    "pm": "write",
    "cto": "full"
  }
}
```

In this example:
- BA and PM can create/update (write) in addition to reading
- CTO has full access including admin tools
- All other agents (researcher, architect, engineer, QA) get the default `read`

### Level 3: Tool-Level Override

Disable specific tools or restrict them to certain agents:

```json
{
  "tool_permissions": [
    {
      "tool_name": "delete_page",
      "allowed": false
    },
    {
      "tool_name": "create_issue",
      "allowed": true,
      "allowed_agents": ["pm", "qa"]
    }
  ]
}
```

This:
- Disables `delete_page` for everyone, regardless of their permission level
- Restricts `create_issue` to only PM and QA, even if other agents have write permission

## Tool Classification

Tools are automatically classified based on their name and description:

### Read Tools
Pattern match: `search`, `get`, `list`, `fetch`, `read`, `query`, `find`

Examples: `search_pages`, `get_issue`, `list_projects`, `fetch_document`

### Write Tools
Pattern match: `create`, `update`, `add`, `set`, `post`, `put`, `edit`, `modify`, `write`, `send`, `submit`

Examples: `create_page`, `update_issue`, `add_comment`, `send_message`

### Admin Tools
Pattern match: `delete`, `remove`, `archive`, `destroy`, `drop`, `purge`

Examples: `delete_page`, `remove_member`, `archive_project`

### Fallback

If a tool name doesn't match any pattern, the description is checked. If neither matches, it defaults to `read` (most restrictive default is safest).

## Permission Resolution Algorithm

When determining if an agent can use a tool:

```python
def can_agent_use_tool(agent_role, tool, connection):
    # 1. Check tool-level override
    for tp in connection.tool_permissions:
        if tp.tool_name == tool.name:
            if not tp.allowed:
                return False
            if tp.allowed_agents and agent_role not in tp.allowed_agents:
                return False

    # 2. Get effective permission level
    if agent_role in connection.agent_permissions:
        perm = connection.agent_permissions[agent_role]
    else:
        perm = connection.default_permission

    # 3. Check classification against permission
    classification = classify_tool(tool.name, tool.description)
    required = {"read": READ, "write": WRITE, "admin": FULL}[classification]
    return perm.allows(required)
```

## Default Service Permissions

Each service has sensible defaults defined in `SERVICE_PRESETS`:

### Notion
```
default: read
BA: write, Researcher: read, Architect: read, PM: write, QA: read, CTO: read
```

### Linear
```
default: read
BA: read, Researcher: read, Architect: read, PM: write, QA: write, CTO: read
```

### Figma
```
default: none
Architect: read, Engineer: read
```

### Jira
```
default: read
BA: read, Researcher: read, Architect: read, PM: write, QA: write, CTO: read
```

### Google Drive
```
default: read (all agents)
```

## Automation Permissions

Pipeline hooks have their own automation flags that control automatic actions:

| Flag | Default | What It Does |
|------|---------|--------------|
| `auto_search_context` | On | Search for related docs/tickets on pipeline start |
| `auto_create_spec_page` | On | Create Notion spec page after BA stage |
| `auto_create_tickets` | On | Create Linear/Jira tickets after PM stage |
| `auto_update_tickets` | On | Mark tickets Done on pipeline completion |
| `auto_create_bug_tickets` | On | Create bug tickets from QA findings |

These are separate from tool permissions. An agent can have write permission to manually create tickets, while the automatic ticket creation hook can be disabled independently.

## Viewing Effective Permissions

The API endpoint `GET /api/connections/{id}/tools?agent_role=pm` returns the tool list with `allowed` status resolved for the specified agent. This is what the UI uses to show which tools each agent can access.
