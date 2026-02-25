-- MCP connections: external service integrations via Model Context Protocol
--
-- Each row represents a configured connection to an external MCP server
-- (Notion, Linear, Figma, Jira, Google Drive, etc.).  Credentials are
-- stored encrypted in the org_secrets table, referenced by credential_secret_id.

CREATE TABLE IF NOT EXISTS mcp_connections (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                TEXT NOT NULL,
    service               TEXT NOT NULL,         -- 'notion', 'linear', 'figma', 'jira', 'google_drive'
    display_name          TEXT NOT NULL,          -- human-friendly label
    transport             TEXT NOT NULL,          -- 'stdio', 'sse', 'streamable_http'
    server_url            TEXT,                   -- for hosted MCP servers (SSE / streamable HTTP)
    command               TEXT,                   -- for stdio servers (e.g. "npx")
    args                  TEXT[] DEFAULT '{}',    -- command arguments
    env                   JSONB  DEFAULT '{}',    -- extra env vars passed to stdio process
    auth_type             TEXT NOT NULL DEFAULT 'token',  -- 'token', 'oauth'
    credential_secret_key TEXT,                   -- key in org_secrets (e.g. 'mcp_notion_token')
    default_permission    TEXT NOT NULL DEFAULT 'read',   -- 'none','read','write','full'
    agent_permissions     JSONB DEFAULT '{}',     -- {"ba": "write", "engineer": "read"}
    tool_permissions      JSONB DEFAULT '[]',     -- fine-grained tool overrides
    enabled               BOOLEAN DEFAULT TRUE,
    last_connected_at     TIMESTAMPTZ,
    discovered_tools      JSONB DEFAULT '[]',     -- cached tool schemas from list_tools()
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcp_connections_org ON mcp_connections (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_connections_org_name
    ON mcp_connections (org_id, display_name);
