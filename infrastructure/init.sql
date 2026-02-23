-- Create the forge application database
CREATE DATABASE forge_app;

-- Create the Langfuse observability database
CREATE DATABASE langfuse;

-- Connect to forge_app and set up schema
\c forge_app

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Pipeline runs: tracks each pipeline execution with JSONB columns per artifact stage
CREATE TABLE pipeline_runs (
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

CREATE INDEX idx_pipeline_runs_status ON pipeline_runs (status);
CREATE INDEX idx_pipeline_runs_pipeline_id ON pipeline_runs (pipeline_id);

-- Ticket executions: tracks individual ticket-level work within a pipeline
CREATE TABLE ticket_executions (
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

CREATE INDEX idx_ticket_executions_pipeline ON ticket_executions (pipeline_id);
CREATE INDEX idx_ticket_executions_status ON ticket_executions (status);

-- Agent events: append-only log of all agent actions (time-series style)
CREATE TABLE agent_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    stage       TEXT,
    agent_role  TEXT,
    agent_id    TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding   vector(1536)
);

-- Time-series index: optimized for queries filtering by time range and agent
CREATE INDEX idx_agent_events_time ON agent_events (created_at DESC);
CREATE INDEX idx_agent_events_pipeline ON agent_events (pipeline_id, created_at DESC);
CREATE INDEX idx_agent_events_type ON agent_events (event_type);

-- CTO interventions: human-in-the-loop escalation records
CREATE TABLE cto_interventions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id         TEXT NOT NULL,
    trigger_type        TEXT NOT NULL,
    trigger_description TEXT NOT NULL DEFAULT '',
    decision            JSONB NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);

CREATE INDEX idx_cto_interventions_status ON cto_interventions (status);
CREATE INDEX idx_cto_interventions_pipeline ON cto_interventions (pipeline_id);

-- Semantic memory store: agent lessons and decisions (fallback for Mem0)
CREATE TABLE memory_store (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_role  TEXT,
    pipeline_id TEXT,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'lesson',
    metadata    JSONB NOT NULL DEFAULT '{}',
    embedding   vector(384),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_memory_store_role ON memory_store (agent_role);
CREATE INDEX idx_memory_store_pipeline ON memory_store (pipeline_id);
CREATE INDEX idx_memory_store_type ON memory_store (memory_type);
CREATE INDEX idx_memory_store_embedding ON memory_store
    USING hnsw (embedding vector_cosine_ops);
