import type { AgentRole } from "./agent";

export type PipelineStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "paused"
  | "awaiting_approval";

export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface PipelineStep {
  id: string;
  name: string;
  agentRole: AgentRole;
  status: StepStatus;
  startedAt?: string;
  completedAt?: string;
  dependsOn: string[];
  cost?: number;
}

export interface PipelineCost {
  total: number;
  budget?: number;
  perAgent: Partial<Record<AgentRole, number>>;
}

export interface PipelineRun {
  id: string;
  name: string;
  status: PipelineStatus;
  steps: PipelineStep[];
  startedAt: string;
  completedAt?: string;
  spec?: string;
  repo?: string;
  branch?: string;
  cost?: PipelineCost;
}

export interface PipelineEvent {
  pipelineId: string;
  runId: string;
  type: "step_started" | "step_completed" | "step_failed" | "pipeline_completed" | "pipeline_failed" | "approval_needed";
  stepId?: string;
  agentRole?: AgentRole;
  details?: Record<string, unknown>;
  timestamp: string;
}
