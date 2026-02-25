-- 010_prompt_versions.sql — Versioned prompt management and evaluation tracking
--
-- prompt_versions: stores each revision of an agent's system prompt, per org.
-- prompt_evaluations: records how a prompt version performed on each pipeline run.

CREATE TABLE IF NOT EXISTS prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    stage           INT NOT NULL,
    agent_role      TEXT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    system_prompt   TEXT NOT NULL,
    change_summary  TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_prompt_version UNIQUE (org_id, stage, version)
);

-- Fast lookup: active prompt per org/stage
CREATE INDEX IF NOT EXISTS idx_prompt_versions_active
    ON prompt_versions (org_id, stage) WHERE is_active = TRUE;

-- Version history listing
CREATE INDEX IF NOT EXISTS idx_prompt_versions_history
    ON prompt_versions (org_id, stage, version DESC);


CREATE TABLE IF NOT EXISTS prompt_evaluations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            TEXT NOT NULL,
    prompt_version_id UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
    pipeline_id       TEXT NOT NULL,
    stage             INT NOT NULL,
    agent_role        TEXT NOT NULL,
    verdict           TEXT,                  -- 'approved', 'needs_revision', 'rejected', NULL
    attempts          INT NOT NULL DEFAULT 1,
    cost_usd          FLOAT NOT NULL DEFAULT 0.0,
    duration_seconds  FLOAT NOT NULL DEFAULT 0.0,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-version aggregation queries
CREATE INDEX IF NOT EXISTS idx_prompt_eval_version
    ON prompt_evaluations (prompt_version_id);

-- Pipeline lookup
CREATE INDEX IF NOT EXISTS idx_prompt_eval_pipeline
    ON prompt_evaluations (pipeline_id, stage);
