import type {
  AdminConfig,
  AdminModels,
  AdminStats,
  AgentEvent,
  ApprovalRequest,
  CostBreakdown,
  CostSummary,
  MemoryDecision,
  MemoryLesson,
  MemoryStats,
  Pipeline,
  PipelineDetail,
  PipelineState,
  StartPipelineRequest,
  TicketExecution,
} from '../types/pipeline.ts'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  // Redirect to login on authentication failure
  if (res.status === 401) {
    window.location.href = '/login'
    throw new Error('Session expired')
  }

  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Pipeline CRUD
// ---------------------------------------------------------------------------

export function listPipelines(): Promise<Pipeline[]> {
  return request('/api/pipelines')
}

export function getPipeline(pipelineId: string): Promise<PipelineDetail> {
  return request(`/api/pipelines/${pipelineId}`)
}

export function getPipelineEvents(pipelineId: string): Promise<AgentEvent[]> {
  return request(`/api/pipelines/${pipelineId}/events`)
}

export function getPipelineTickets(
  pipelineId: string,
): Promise<TicketExecution[]> {
  return request(`/api/pipelines/${pipelineId}/tickets`)
}

export function getPipelineState(pipelineId: string): Promise<PipelineState> {
  return request(`/api/pipelines/${pipelineId}/state`)
}

// ---------------------------------------------------------------------------
// Pipeline actions
// ---------------------------------------------------------------------------

export function startPipeline(
  body: StartPipelineRequest,
): Promise<{ pipeline_id: string; workflow_id: string; status: string }> {
  return request('/api/pipelines', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function approvePipeline(
  pipelineId: string,
  body: ApprovalRequest,
): Promise<{ pipeline_id: string; action: string; stage: string }> {
  return request(`/api/pipelines/${pipelineId}/approve`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rejectPipeline(
  pipelineId: string,
  body: ApprovalRequest,
): Promise<{ pipeline_id: string; action: string; stage: string }> {
  return request(`/api/pipelines/${pipelineId}/reject`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function abortPipeline(
  pipelineId: string,
  reason = 'Aborted from dashboard',
): Promise<{ pipeline_id: string; action: string }> {
  return request(`/api/pipelines/${pipelineId}/abort`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export function getMemoryLessons(
  agentRole?: string,
  limit = 20,
): Promise<MemoryLesson[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (agentRole) params.set('agent_role', agentRole)
  return request(`/api/memory/lessons?${params}`)
}

export function getMemoryDecisions(limit = 20): Promise<MemoryDecision[]> {
  return request(`/api/memory/decisions?limit=${limit}`)
}

export function getMemoryStats(): Promise<MemoryStats> {
  return request('/api/memory/stats')
}

export function createMemoryLesson(
  content: string,
  agentRole = 'manual',
): Promise<{ id: string; content: string; agent_role: string; created_at: string }> {
  return request('/api/memory/lessons', {
    method: 'POST',
    body: JSON.stringify({ content, agent_role: agentRole }),
  })
}

export function deleteMemoryLesson(
  lessonId: string,
): Promise<{ deleted: string }> {
  return request(`/api/memory/lessons/${lessonId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Pipeline messages (multiplayer chat)
// ---------------------------------------------------------------------------

export interface PipelineMessage {
  id: string
  pipeline_id: string
  user_id: string
  user_name: string
  content: string
  message_type: string
  created_at: string
}

export function listPipelineMessages(
  pipelineId: string,
  limit = 100,
): Promise<PipelineMessage[]> {
  return request(`/api/pipelines/${pipelineId}/messages?limit=${limit}`)
}

export function createPipelineMessage(
  pipelineId: string,
  content: string,
  messageType = 'chat',
): Promise<PipelineMessage> {
  return request(`/api/pipelines/${pipelineId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content, message_type: messageType }),
  })
}

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------

export function getCostSummary(pipelineId: string): Promise<CostSummary> {
  return request(`/api/observability/cost-summary/${pipelineId}`)
}

// ---------------------------------------------------------------------------
// Concurrency
// ---------------------------------------------------------------------------

export interface ConcurrencyMetrics {
  pipeline_id: string
  active_engineers: number
  active_qa: number
  active_groups: number
  max_concurrent_engineers: number
  max_concurrent_qa: number
  max_concurrent_groups: number
  active_engineer_tickets: string[]
  active_qa_tickets: string[]
  system_load: number
  backpressure_threshold: number
  backpressure_active: boolean
  avg_ticket_duration_seconds: number | null
  completed_tickets: number
  current_group_index: number | null
  total_groups: number
  estimated_remaining_seconds: number | null
  ticket_timeout_minutes: number
  group_timeout_minutes: number
  max_retries_per_ticket: number
}

export function getConcurrencyMetrics(
  pipelineId: string,
): Promise<ConcurrencyMetrics> {
  return request(`/api/pipelines/${pipelineId}/concurrency`)
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export function getAdminStats(): Promise<AdminStats> {
  return request('/api/admin/stats')
}

export function getAdminModels(): Promise<AdminModels> {
  return request('/api/admin/models')
}

export function getAdminConfig(): Promise<AdminConfig> {
  return request('/api/admin/config')
}

export function updateAdminConfig(
  body: Partial<AdminConfig>,
): Promise<{ status: string; config: Record<string, unknown> }> {
  return request('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getPipelineErrors(
  pipelineId: string,
): Promise<AgentEvent[]> {
  return request(`/api/pipelines/${pipelineId}/errors`)
}

export function getPipelineCostBreakdown(
  pipelineId: string,
): Promise<CostBreakdown> {
  return request(`/api/pipelines/${pipelineId}/cost-breakdown`)
}

export function retryPipelineStage(
  pipelineId: string,
  stage: string,
  modifiedInput?: Record<string, unknown>,
): Promise<{ pipeline_id: string; action: string; stage: string }> {
  return request(`/api/pipelines/${pipelineId}/retry-stage`, {
    method: 'POST',
    body: JSON.stringify({
      stage,
      modified_input: modifiedInput ?? null,
    }),
  })
}

// ---------------------------------------------------------------------------
// Org Settings
// ---------------------------------------------------------------------------

export interface OrgSettings {
  org_id: string
  max_pipeline_cost_usd: number
  max_concurrent_pipelines: number
  auto_approve_stages: string[]
  default_model_tier: string
  pr_strategy: string
  memory_sharing_mode: string
}

export function getOrgSettings(): Promise<OrgSettings> {
  return request('/api/settings')
}

export function updateOrgSettings(
  body: Partial<Omit<OrgSettings, 'org_id'>>,
): Promise<OrgSettings> {
  return request('/api/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

// ---------------------------------------------------------------------------
// Org Secrets
// ---------------------------------------------------------------------------

export interface OrgSecretKey {
  key: string
  updated_at: string
  created_by: string
}

export function listSecrets(): Promise<{ org_id: string; keys: OrgSecretKey[] }> {
  return request('/api/secrets')
}

export function setSecret(
  key: string,
  value: string,
): Promise<{ org_id: string; key: string; status: string }> {
  return request(`/api/secrets/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
  })
}

export function deleteSecret(
  key: string,
): Promise<{ org_id: string; key: string; status: string }> {
  return request(`/api/secrets/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
}

// ---------------------------------------------------------------------------
// Org GitHub Identities
// ---------------------------------------------------------------------------

export interface OrgIdentity {
  id: string
  org_id: string
  name: string
  github_username: string
  email: string
  github_org: string | null
  is_default: boolean
  created_at: string
}

export function listIdentities(): Promise<OrgIdentity[]> {
  return request('/api/identities')
}

export function createIdentity(body: {
  name: string
  github_username: string
  email: string
  github_token?: string
  ssh_key?: string
  github_org?: string
  is_default?: boolean
}): Promise<OrgIdentity> {
  return request('/api/identities', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function deleteIdentity(
  identityId: string,
): Promise<{ status: string }> {
  return request(`/api/identities/${identityId}`, {
    method: 'DELETE',
  })
}

export function testIdentity(
  identityId: string,
): Promise<{ identity_id: string; github_username: string; status: string; detail: string }> {
  return request(`/api/identities/${identityId}/test`, {
    method: 'POST',
  })
}
