/** Pipeline list item returned by GET /api/pipelines */
export interface Pipeline {
  id: string
  pipeline_id: string
  status: string
  current_stage: string
  created_at: string
  total_cost_usd: number
}

/** Full pipeline detail returned by GET /api/pipelines/:id */
export interface PipelineDetail extends Pipeline {
  updated_at: string | null
  business_spec: string
  project_name: string
  product_spec: Record<string, unknown> | null
  enriched_spec: Record<string, unknown> | null
  tech_spec: Record<string, unknown> | null
  prd_board: Record<string, unknown> | null
}

/** Agent event from GET /api/pipelines/:id/events or WebSocket */
export interface AgentEvent {
  id: string
  pipeline_id: string
  event_type: string
  stage: string | null
  agent_role: string | null
  agent_id: string | null
  payload: Record<string, unknown>
  created_at: string
  /** Present on WebSocket messages, absent from DB rows */
  timestamp?: string
}

/** Ticket execution from GET /api/pipelines/:id/tickets */
export interface TicketExecution {
  id: string
  pipeline_id: string
  ticket_key: string
  status: string
  verdict: string | null
  code_artifact: Record<string, unknown> | null
  qa_review: Record<string, unknown> | null
  attempts: number
  created_at: string
  updated_at: string | null
}

/** Live workflow state from GET /api/pipelines/:id/state */
export interface PipelineState {
  pipeline_id: string
  current_stage: string
  total_cost_usd: number
  max_cost_usd: number
  aborted: boolean
  abort_reason: string
  pending_approval: string | null
  product_spec: Record<string, unknown> | null
  enriched_spec: Record<string, unknown> | null
  tech_spec: Record<string, unknown> | null
  prd_board: Record<string, unknown> | null
  repo_path: string
  code_artifacts: Record<string, unknown>[]
  qa_reviews: Record<string, unknown>[]
}

/** Body for POST /api/pipelines */
export interface StartPipelineRequest {
  business_spec: string
  project_name?: string
  repo_url?: string
  identity?: string
  issue_number?: number
  pr_strategy?: 'single_pr' | 'pr_per_ticket' | 'direct_push'
}

/** Body for POST /api/pipelines/:id/approve or reject */
export interface ApprovalRequest {
  stage: string
  notes?: string
  approved_by?: string
}

/** Memory lesson from GET /api/memory/lessons */
export interface MemoryLesson {
  id: string
  agent_role: string | null
  pipeline_id: string | null
  user_id: string | null
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

/** Memory decision from GET /api/memory/decisions */
export interface MemoryDecision {
  id: string
  agent_role: string | null
  pipeline_id: string | null
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

/** Memory statistics from GET /api/memory/stats */
export interface MemoryStats {
  total_lessons: number
  total_decisions: number
  lessons_per_role: Record<string, number>
  contributions_per_user?: Record<string, number>
  recent_lessons?: {
    id: string
    content: string
    agent_role: string | null
    user_id: string | null
    created_at: string | null
  }[]
  recent_topics?: string[]
}

/** Cost summary from GET /api/observability/cost-summary/:id */
export interface CostSummary {
  pipeline_id: string
  project_name: string
  total_cost_usd: number
  status: string
  stages: { stage: string; event_count: number }[]
  tickets: {
    ticket_key: string
    status: string
    attempts: number
    cost_usd: number
  }[]
}

// ---------------------------------------------------------------------------
// Admin types
// ---------------------------------------------------------------------------

/** System-wide stats from GET /api/admin/stats */
export interface AdminStats {
  total_pipelines: number
  succeeded: number
  failed: number
  success_rate: number
  total_cost_usd: number
  avg_cost_usd: number
  avg_duration_seconds: number
  failure_stages: { stage: string; count: number }[]
  model_usage: Record<string, { calls: number; percentage: number }>
}

/** Per-model info from GET /api/admin/models */
export interface ModelHealth {
  available: boolean
  is_local: boolean
  avg_latency_ms: number
  error_rate: number
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  pricing_input_per_mtok: number
  pricing_output_per_mtok: number
}

export interface AdminModels {
  models: Record<string, ModelHealth>
  local_model_available: boolean
}

/** Pipeline config from GET/POST /api/admin/config */
export interface AdminConfig {
  max_concurrent_engineers: number
  max_qa_cycles: number
  auto_merge: boolean
  model_overrides: Record<string, string>
}

/** Cost breakdown from GET /api/pipelines/:id/cost-breakdown */
export interface CostBreakdown {
  pipeline_id: string
  total_cost_usd: number
  status: string
  by_stage: {
    stage: string
    cost_usd: number
    event_count: number
    avg_duration_seconds: number
  }[]
  by_ticket: {
    ticket_key: string
    status: string
    attempts: number
    cost_usd: number
  }[]
  by_model: {
    model: string
    calls: number
    cost_usd: number
    input_tokens: number
    output_tokens: number
  }[]
}
