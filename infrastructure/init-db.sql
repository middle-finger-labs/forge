-- Forge base schema (Railway-compatible: no \c, no CREATE DATABASE)
-- The DATABASE_URL already points at the correct database.

-- Try to enable pgvector; skip gracefully if not available.
-- Embedding columns will be added by a separate migration when pgvector is ready.
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'pgvector not available — skipping (embeddings disabled)';
END $$;

-- Migrations tracking table
CREATE TABLE IF NOT EXISTS _migrations (
    id         SERIAL PRIMARY KEY,
    filename   TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pipeline runs: tracks each pipeline execution with JSONB columns per artifact stage
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id     TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'pending',
    current_stage   TEXT NOT NULL DEFAULT 'intake',
    business_spec   TEXT NOT NULL DEFAULT '',
    project_name    TEXT NOT NULL DEFAULT '',
    total_cost_usd  NUMERIC NOT NULL DEFAULT 0.0,
    product_spec    JSONB,
    enriched_spec   JSONB,
    tech_spec       JSONB,
    prd_board       JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs (status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline_id ON pipeline_runs (pipeline_id);

-- Ticket executions: tracks individual ticket-level work within a pipeline
CREATE TABLE IF NOT EXISTS ticket_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id     TEXT NOT NULL,
    ticket_key      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    verdict         TEXT,
    agent_id        TEXT,
    branch_name     TEXT,
    code_artifact   JSONB,
    qa_review       JSONB,
    attempts        INT NOT NULL DEFAULT 0,
    cost_usd        NUMERIC NOT NULL DEFAULT 0.0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pipeline_id, ticket_key)
);

CREATE INDEX IF NOT EXISTS idx_ticket_executions_pipeline ON ticket_executions (pipeline_id);
CREATE INDEX IF NOT EXISTS idx_ticket_executions_status ON ticket_executions (status);

-- Agent events: append-only log of all agent actions (time-series style)
-- Note: embedding column added conditionally below (requires pgvector)
CREATE TABLE IF NOT EXISTS agent_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    stage       TEXT,
    agent_role  TEXT,
    agent_id    TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_events_time ON agent_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_pipeline ON agent_events (pipeline_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events (event_type);

-- CTO interventions: human-in-the-loop escalation records
CREATE TABLE IF NOT EXISTS cto_interventions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id         TEXT NOT NULL,
    trigger_type        TEXT NOT NULL,
    trigger_description TEXT NOT NULL DEFAULT '',
    decision            JSONB NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cto_interventions_status ON cto_interventions (status);
CREATE INDEX IF NOT EXISTS idx_cto_interventions_pipeline ON cto_interventions (pipeline_id);

-- Semantic memory store: agent lessons and decisions (fallback for Mem0)
-- Note: embedding column added conditionally below (requires pgvector)
CREATE TABLE IF NOT EXISTS memory_store (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_role  TEXT,
    pipeline_id TEXT,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'lesson',
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_store_role ON memory_store (agent_role);
CREATE INDEX IF NOT EXISTS idx_memory_store_pipeline ON memory_store (pipeline_id);
CREATE INDEX IF NOT EXISTS idx_memory_store_type ON memory_store (memory_type);

-- Add vector columns and HNSW index only if pgvector is available
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
    ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS embedding vector(1536);
    ALTER TABLE memory_store ADD COLUMN IF NOT EXISTS embedding vector(384);
    CREATE INDEX IF NOT EXISTS idx_memory_store_embedding ON memory_store
        USING hnsw (embedding vector_cosine_ops);
  END IF;
END $$;
