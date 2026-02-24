-- 003_pipeline_messages.sql
-- Persistent chat messages for multiplayer pipeline collaboration.

CREATE TABLE IF NOT EXISTS pipeline_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id  TEXT NOT NULL,
    org_id       TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    user_name    TEXT NOT NULL,
    content      TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'chat',  -- 'chat', 'approval', 'rejection', 'system'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_messages_pipeline
    ON pipeline_messages (pipeline_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_messages_org
    ON pipeline_messages (org_id);
