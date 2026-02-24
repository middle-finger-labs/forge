-- 004_org_secrets.sql
-- Per-org secrets, settings, and GitHub identities for multi-tenant configuration.

-- Encrypted secrets (API keys, tokens)
CREATE TABLE IF NOT EXISTS org_secrets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    key             TEXT NOT NULL,                    -- "ANTHROPIC_API_KEY", "GITHUB_TOKEN_PERSONAL"
    encrypted_value BYTEA NOT NULL,
    created_by      TEXT NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, key)
);

CREATE INDEX IF NOT EXISTS idx_org_secrets_org ON org_secrets (org_id);

-- Org-level pipeline settings
CREATE TABLE IF NOT EXISTS org_settings (
    org_id                     TEXT PRIMARY KEY,
    max_pipeline_cost_usd      FLOAT DEFAULT 50.0,
    max_concurrent_pipelines   INT DEFAULT 3,
    auto_approve_stages        TEXT[] DEFAULT '{}',   -- stages that skip human approval
    default_model_tier         TEXT DEFAULT 'strong',  -- frontier/strong/local_coder
    pr_strategy                TEXT DEFAULT 'single_pr',
    created_at                 TIMESTAMPTZ DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ DEFAULT NOW()
);

-- GitHub identities per org (replaces local YAML for hosted mode)
CREATE TABLE IF NOT EXISTS org_identities (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  TEXT NOT NULL,
    name                    TEXT NOT NULL,
    github_username         TEXT NOT NULL,
    email                   TEXT NOT NULL,
    ssh_key_encrypted       BYTEA,              -- encrypted private key (optional, for hosted)
    github_token_encrypted  BYTEA,              -- encrypted PAT
    github_org              TEXT,
    is_default              BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, name)
);

CREATE INDEX IF NOT EXISTS idx_org_identities_org ON org_identities (org_id);
