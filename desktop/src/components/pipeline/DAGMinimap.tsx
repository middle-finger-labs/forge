import { AGENT_REGISTRY } from "@/types/agent";
import type { PipelineRun, PipelineStep, StepStatus } from "@/types/pipeline";
import { Clock, DollarSign } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status colors ───────────────────────────────────

const NODE_STATUS: Record<
  StepStatus,
  { bg: string; border: string; ring: string; label: string }
> = {
  completed: {
    bg: "bg-[var(--forge-success)]",
    border: "border-[var(--forge-success)]",
    ring: "ring-[var(--forge-success)]/20",
    label: "Completed",
  },
  running: {
    bg: "bg-[var(--forge-accent)]",
    border: "border-[var(--forge-accent)]",
    ring: "ring-[var(--forge-accent)]/20",
    label: "Running",
  },
  pending: {
    bg: "bg-gray-500",
    border: "border-gray-500/40",
    ring: "ring-gray-500/10",
    label: "Pending",
  },
  failed: {
    bg: "bg-[var(--forge-error)]",
    border: "border-[var(--forge-error)]",
    ring: "ring-[var(--forge-error)]/20",
    label: "Failed",
  },
  skipped: {
    bg: "bg-gray-600",
    border: "border-gray-600/40",
    ring: "ring-gray-600/10",
    label: "Skipped",
  },
};

const CONNECTOR_COLOR: Record<StepStatus, string> = {
  completed: "bg-[var(--forge-success)]",
  running: "bg-[var(--forge-accent)]",
  pending: "bg-[var(--forge-border)]",
  failed: "bg-[var(--forge-error)]",
  skipped: "bg-[var(--forge-border)]",
};

// ─── Props ───────────────────────────────────────────

interface DAGMinimapProps {
  pipelineRun: PipelineRun;
  onNodeClick?: (stepId: string, agentRole: string) => void;
}

// ─── DAGMinimap ──────────────────────────────────────

export function DAGMinimap({ pipelineRun, onNodeClick }: DAGMinimapProps) {
  const totalCost = pipelineRun.cost?.total ?? 0;
  const budget = pipelineRun.cost?.budget;
  const elapsed = getElapsedTime(pipelineRun.startedAt, pipelineRun.completedAt);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          Pipeline DAG
        </h3>
        <span
          className={cn(
            "text-[10px] font-medium px-1.5 py-0.5 rounded capitalize",
            pipelineRun.status === "running" &&
              "bg-[var(--forge-accent)]/10 text-[var(--forge-accent)]",
            pipelineRun.status === "completed" &&
              "bg-[var(--forge-success)]/10 text-[var(--forge-success)]",
            pipelineRun.status === "failed" &&
              "bg-[var(--forge-error)]/10 text-[var(--forge-error)]",
            pipelineRun.status === "paused" &&
              "bg-[var(--forge-warning)]/10 text-[var(--forge-warning)]",
            pipelineRun.status === "awaiting_approval" &&
              "bg-[var(--forge-warning)]/10 text-[var(--forge-warning)]",
            pipelineRun.status === "pending" &&
              "text-[var(--forge-text-muted)]"
          )}
        >
          {pipelineRun.status.replace("_", " ")}
        </span>
      </div>

      {/* Summary stats */}
      <div className="flex items-center gap-3 text-[11px]">
        <span className="flex items-center gap-1 text-[var(--forge-text-muted)]">
          <Clock className="w-3 h-3" />
          {elapsed}
        </span>
        {totalCost > 0 && (
          <span className="flex items-center gap-1 text-[var(--forge-text-muted)]">
            <DollarSign className="w-3 h-3" />
            <span className="font-mono">${totalCost.toFixed(3)}</span>
            {budget != null && (
              <span className="text-[var(--forge-text-muted)]/60">
                / ${budget.toFixed(2)}
              </span>
            )}
          </span>
        )}
      </div>

      {/* Progress bar */}
      <ProgressBar steps={pipelineRun.steps} />

      {/* Node list */}
      <div className="space-y-0.5">
        {pipelineRun.steps.map((step, i) => (
          <DAGNode
            key={step.id}
            step={step}

            isLast={i === pipelineRun.steps.length - 1}
            cost={pipelineRun.cost?.perAgent[step.agentRole]}
            onClick={() => onNodeClick?.(step.id, step.agentRole)}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 pt-2 border-t border-[var(--forge-border)]">
        {(["completed", "running", "pending", "failed", "skipped"] as StepStatus[]).map(
          (status) => (
            <span key={status} className="flex items-center gap-1 text-[10px] text-[var(--forge-text-muted)]">
              <span className={cn("w-2 h-2 rounded-full", NODE_STATUS[status].bg)} />
              {NODE_STATUS[status].label}
            </span>
          )
        )}
      </div>
    </div>
  );
}

// ─── Progress bar ────────────────────────────────────

function ProgressBar({ steps }: { steps: PipelineStep[] }) {
  const completed = steps.filter((s) => s.status === "completed").length;
  const total = steps.length;
  const pct = total > 0 ? (completed / total) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[10px] text-[var(--forge-text-muted)]">
        <span>
          {completed}/{total} steps
        </span>
        <span>{Math.round(pct)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--forge-border)] overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            completed === total
              ? "bg-[var(--forge-success)]"
              : "bg-[var(--forge-accent)]"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── DAG node ────────────────────────────────────────

function DAGNode({
  step,
  isLast,
  cost,
  onClick,
}: {
  step: PipelineStep;
  isLast: boolean;
  cost?: number;
  onClick: () => void;
}) {
  const info = AGENT_REGISTRY[step.agentRole];
  const status = NODE_STATUS[step.status];
  const elapsed = step.startedAt
    ? getElapsedTime(step.startedAt, step.completedAt)
    : null;

  return (
    <div className="flex">
      {/* Timeline column */}
      <div className="flex flex-col items-center w-6 shrink-0">
        {/* Node dot */}
        <div
          className={cn(
            "w-4 h-4 rounded-full border-2 ring-2 shrink-0 mt-2",
            status.border,
            status.ring,
            step.status === "running" && "animate-pulse"
          )}
        >
          <div
            className={cn("w-full h-full rounded-full", status.bg)}
          />
        </div>
        {/* Connector line */}
        {!isLast && (
          <div
            className={cn(
              "w-0.5 flex-1 min-h-[12px]",
              CONNECTOR_COLOR[step.status]
            )}
          />
        )}
      </div>

      {/* Node content */}
      <button
        onClick={onClick}
        className={cn(
          "flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg ml-1 mb-0.5",
          "hover:bg-[var(--forge-hover)] transition-colors text-left group",
          step.status === "skipped" && "opacity-50"
        )}
      >
        <span className="text-sm shrink-0">{info?.emoji ?? "\u{1F916}"}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "text-xs font-medium truncate",
                step.status === "skipped"
                  ? "line-through text-[var(--forge-text-muted)]"
                  : "text-white"
              )}
            >
              {step.name}
            </span>
            <span className="text-[10px] text-[var(--forge-text-muted)] capitalize shrink-0">
              {step.status}
            </span>
          </div>
          {/* Meta row */}
          <div className="flex items-center gap-2 mt-0.5">
            {elapsed && (
              <span className="text-[10px] text-[var(--forge-text-muted)] flex items-center gap-0.5">
                <Clock className="w-2.5 h-2.5" />
                {elapsed}
              </span>
            )}
            {cost != null && cost > 0 && (
              <span className="text-[10px] text-[var(--forge-text-muted)] font-mono">
                ${cost.toFixed(3)}
              </span>
            )}
          </div>
        </div>
      </button>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────

function getElapsedTime(startIso: string, endIso?: string): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const diff = Math.max(0, end - start);
  const seconds = Math.floor(diff / 1000);

  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
