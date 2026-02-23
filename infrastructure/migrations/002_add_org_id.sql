-- 002_add_org_id.sql
-- Add organization scoping to forge's core tables for multi-tenancy.
-- org_id references the Better Auth organization that owns the record.
-- NULL org_id means the record was created before multi-tenancy (legacy).

\c forge_app

ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS org_id TEXT;
ALTER TABLE agent_events ADD COLUMN IF NOT EXISTS org_id TEXT;
ALTER TABLE ticket_executions ADD COLUMN IF NOT EXISTS org_id TEXT;
ALTER TABLE cto_interventions ADD COLUMN IF NOT EXISTS org_id TEXT;
ALTER TABLE memory_store ADD COLUMN IF NOT EXISTS org_id TEXT;

-- Indexes for org-scoped queries
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_org ON pipeline_runs(org_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_org ON agent_events(org_id);
CREATE INDEX IF NOT EXISTS idx_ticket_executions_org ON ticket_executions(org_id);
CREATE INDEX IF NOT EXISTS idx_cto_interventions_org ON cto_interventions(org_id);
CREATE INDEX IF NOT EXISTS idx_memory_store_org ON memory_store(org_id);
