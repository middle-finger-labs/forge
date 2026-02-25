-- 009_lessons.sql — Lessons learned from user feedback on agent outputs
--
-- Stores generalizable lessons per org, scoped by agent_role and lesson_type.
-- Uses pgvector (384-dim) for semantic retrieval so agents can find relevant
-- lessons when building prompts.

CREATE TABLE IF NOT EXISTS lessons (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            TEXT NOT NULL,
    agent_role        TEXT NOT NULL,
    lesson_type       TEXT NOT NULL CHECK (lesson_type IN (
        'code_pattern',
        'architecture',
        'style',
        'requirement',
        'antipattern',
        'testing',
        'review'
    )),
    trigger_context   TEXT NOT NULL,
    lesson            TEXT NOT NULL,
    evidence          TEXT,
    pipeline_id       TEXT,
    confidence        FLOAT NOT NULL DEFAULT 0.8,
    times_applied     INT NOT NULL DEFAULT 0,
    times_reinforced  INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding         vector(384)
);

-- Org-scoped lookups (most queries filter by org_id + agent_role)
CREATE INDEX IF NOT EXISTS idx_lessons_org_role
    ON lessons (org_id, agent_role);

-- Semantic search via HNSW (cosine distance)
CREATE INDEX IF NOT EXISTS idx_lessons_embedding_hnsw
    ON lessons USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Fast confidence-based filtering
CREATE INDEX IF NOT EXISTS idx_lessons_confidence
    ON lessons (org_id, confidence DESC);
