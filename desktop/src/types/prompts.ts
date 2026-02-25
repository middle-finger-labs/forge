export interface PromptVersion {
  id: string;
  org_id: string;
  stage: number;
  agent_role: string;
  version: number;
  system_prompt: string;
  change_summary: string;
  is_active: boolean;
  created_by: string;
  created_at: string | null;
  prompt_hash: string;
}

export interface PromptVersionStats {
  version_id: string;
  total_runs: number;
  approval_rate: number;
  avg_cost_usd: number;
  avg_duration_seconds: number;
  avg_attempts: number;
  error_count: number;
}

export interface StatsHistoryPoint {
  date: string;
  approval_rate: number;
  avg_cost_usd: number;
  run_count: number;
}

export interface DefaultPrompt {
  stage: number;
  agent_role: string;
  prompt_hash: string;
  prompt_length: number;
  preview: string;
}

export interface TestPromptResult {
  output: Record<string, unknown> | null;
  cost_usd: number;
  duration_seconds: number;
  error: string | null;
}

export interface CompareResult {
  version_a: {
    version: number;
    change_summary: string;
    is_active: boolean;
    prompt_hash: string;
    stats: PromptVersionStats;
  };
  version_b: {
    version: number;
    change_summary: string;
    is_active: boolean;
    prompt_hash: string;
    stats: PromptVersionStats;
  };
}

export interface Lesson {
  id: string;
  org_id: string;
  agent_role: string;
  lesson_type: string;
  trigger_context: string;
  lesson: string;
  evidence: string | null;
  pipeline_id: string | null;
  confidence: number;
  times_applied: number;
  times_reinforced: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface UpdateLessonRequest {
  lesson?: string;
  trigger_context?: string;
  lesson_type?: string;
  confidence?: number;
}

export interface AgentStageSummary {
  cost_usd: number;
  duration_seconds: number;
  first_pass: boolean;
  attempts: number;
  lessons_applied: number;
}

export interface PipelineSummary {
  pipeline_id: string;
  total_cost_usd: number;
  total_duration_seconds: number;
  per_agent: Record<string, AgentStageSummary>;
  lessons_applied: Array<{
    lesson_id: string;
    agent_role: string;
    lesson: string;
  }>;
}
