-- Audit log for MCP tool calls — tracks every tool invocation through
-- the client manager for cost tracking, debugging, and compliance.

CREATE TABLE IF NOT EXISTS connection_tool_calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    connection_id   UUID NOT NULL REFERENCES mcp_connections(id) ON DELETE CASCADE,
    pipeline_id     TEXT,                -- nullable: tool calls can happen outside pipelines
    agent_role      TEXT,
    tool_name       TEXT NOT NULL,
    arguments       JSONB,
    result_summary  TEXT,                -- truncated result for audit (first 500 chars)
    success         BOOLEAN NOT NULL,
    duration_ms     INT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_org        ON connection_tool_calls (org_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_connection  ON connection_tool_calls (connection_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_pipeline    ON connection_tool_calls (pipeline_id)
    WHERE pipeline_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tool_calls_created     ON connection_tool_calls (created_at DESC);
