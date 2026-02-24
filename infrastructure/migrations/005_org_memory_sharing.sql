-- 005_org_memory_sharing.sql
-- Add memory sharing mode to org_settings and user_id tracking to memory_store
-- for private memory mode (where each user has their own memory context within an org).

-- Memory sharing mode: "shared" (default) or "private"
ALTER TABLE org_settings
    ADD COLUMN IF NOT EXISTS memory_sharing_mode TEXT DEFAULT 'shared';

-- Track which user created each memory (needed for private mode filtering)
ALTER TABLE memory_store
    ADD COLUMN IF NOT EXISTS user_id TEXT;

CREATE INDEX IF NOT EXISTS idx_memory_store_user ON memory_store (user_id);

-- Composite index for private-mode queries (org + user)
CREATE INDEX IF NOT EXISTS idx_memory_store_org_user ON memory_store (org_id, user_id);
