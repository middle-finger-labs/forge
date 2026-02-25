-- 006_conversations.sql
-- Conversation-based messaging for the desktop app's Slack-like interface.
-- Supports agent DMs, pipeline channels, and general conversations.

-- ─── Conversations ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       TEXT NOT NULL,
    type         TEXT NOT NULL DEFAULT 'general',       -- 'agent_dm', 'pipeline', 'general'
    title        TEXT NOT NULL DEFAULT '',
    agent_role   TEXT,                                  -- set for agent_dm conversations
    pipeline_id  TEXT,                                  -- set for pipeline conversations
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Each org has at most one DM per agent role
    CONSTRAINT uq_org_agent_dm UNIQUE (org_id, agent_role)
);

CREATE INDEX IF NOT EXISTS idx_conversations_org
    ON conversations (org_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_pipeline
    ON conversations (pipeline_id) WHERE pipeline_id IS NOT NULL;

-- ─── Messages ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    org_id          TEXT NOT NULL,

    -- Author (discriminated: user | agent | system)
    author_type     TEXT NOT NULL DEFAULT 'user',       -- 'user', 'agent', 'system'
    author_id       TEXT,                               -- user_id or agent_role
    author_name     TEXT NOT NULL DEFAULT '',

    -- Rich content: JSONB array of content blocks
    -- Each block: {"type": "text", "text": "..."} | {"type": "code", ...} | etc.
    content         JSONB NOT NULL DEFAULT '[]'::jsonb,

    thread_id       UUID,                               -- nullable, for threaded replies
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_thread
    ON messages (thread_id, created_at) WHERE thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_org
    ON messages (org_id);

-- ─── Updated-at trigger ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_conversation_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations SET updated_at = now() WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_message_updates_conversation
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_timestamp();
