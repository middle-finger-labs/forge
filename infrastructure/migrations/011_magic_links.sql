-- 011_magic_links.sql
-- Magic link authentication: passwordless login + org invites

CREATE TABLE IF NOT EXISTS magic_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL,
    token           TEXT NOT NULL UNIQUE,
    server_url      TEXT NOT NULL,
    org_id          TEXT,
    invite_by       TEXT,
    purpose         TEXT NOT NULL CHECK (purpose IN ('login', 'invite')),
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Fast lookup by token (only unused links)
CREATE INDEX idx_magic_links_token ON magic_links(token) WHERE used_at IS NULL;

-- Lookup by email (for rate limiting + user history)
CREATE INDEX idx_magic_links_email ON magic_links(email);

-- Cleanup: expire old links (can be run periodically)
CREATE INDEX idx_magic_links_expires_at ON magic_links(expires_at) WHERE used_at IS NULL;
