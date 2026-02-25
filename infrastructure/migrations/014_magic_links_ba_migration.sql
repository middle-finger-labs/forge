-- 014_magic_links_ba_migration.sql
-- Adapt magic_links table for Better Auth's magicLink plugin integration.
--
-- The token column previously had a UNIQUE constraint, but now we use
-- '__pending__' as a placeholder until BA's sendMagicLink callback fills
-- in the real token.  Multiple rows can have '__pending__' simultaneously.

-- Drop the existing UNIQUE constraint on token
ALTER TABLE magic_links DROP CONSTRAINT IF EXISTS magic_links_token_key;

-- Drop the old partial index if it exists
DROP INDEX IF EXISTS idx_magic_links_token;

-- Add a partial unique index: only enforce uniqueness for real tokens
-- that haven't been consumed yet
CREATE UNIQUE INDEX idx_magic_links_token_unique
    ON magic_links(token)
    WHERE token != '__pending__' AND used_at IS NULL;

-- Re-create the lookup index for unused tokens (excludes __pending__)
CREATE INDEX idx_magic_links_token_lookup
    ON magic_links(token)
    WHERE token != '__pending__' AND used_at IS NULL;
