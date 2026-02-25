import { useState, useMemo, useRef, useCallback } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { usePullToRefresh } from "@/hooks/useMobileGestures";
import { useCollapsibleHeader } from "@/hooks/useCollapsibleHeader";
import { useHaptics } from "@/hooks/useHaptics";
import { StaleIndicator } from "./MobileConnectionBar";
import { PipelineListSkeleton } from "@/components/ui/Skeleton";
import type { PipelineRun, PipelineStatus, StepStatus } from "@/types/pipeline";
import { AGENT_REGISTRY } from "@/types/agent";
import { Zap, Plus, Clock, DollarSign } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status config ──────────────────────────────────

const STATUS_CONFIG: Record<PipelineStatus, { label: string; emoji: string; color: string; bg: string }> = {
  running:            { label: "Running",        emoji: "\u{1F504}", color: "text-[var(--forge-success)]",    bg: "bg-[var(--forge-success)]/10" },
  completed:          { label: "Completed",      emoji: "\u2705",    color: "text-[var(--forge-success)]",    bg: "bg-[var(--forge-success)]/10" },
  failed:             { label: "Failed",         emoji: "\u274C",    color: "text-[var(--forge-error)]",      bg: "bg-[var(--forge-error)]/10" },
  paused:             { label: "Paused",         emoji: "\u23F8\uFE0F", color: "text-[var(--forge-warning)]", bg: "bg-[var(--forge-warning)]/10" },
  awaiting_approval:  { label: "Needs Approval", emoji: "\u{1F514}", color: "text-[var(--forge-warning)]",    bg: "bg-[var(--forge-warning)]/10" },
  pending:            { label: "Pending",        emoji: "\u23F3",    color: "text-[var(--forge-text-muted)]", bg: "bg-[var(--forge-hover)]" },
};

const STEP_DOT_COLOR: Record<StepStatus, string> = {
  completed: "bg-[var(--forge-success)]",
  running:   "bg-[var(--forge-accent)]",
  pending:   "bg-[var(--forge-text-muted)]/30",
  failed:    "bg-[var(--forge-error)]",
  skipped:   "bg-[var(--forge-text-muted)]/20",
};

// ─── Filter tabs ─────────────────────────────────────

type FilterTab = "all" | "active" | "approval" | "completed";

const FILTER_TABS: Array<{ key: FilterTab; label: string }> = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "approval", label: "Needs Approval" },
  { key: "completed", label: "Completed" },
];

// ─── Props ──────────────────────────────────────────

interface MobilePipelineListProps {
  pipelineRuns: PipelineRun[];
  onSelectPipeline: (conversationId: string) => void;
}

// ─── Component ──────────────────────────────────────

export function MobilePipelineList({
  pipelineRuns,
  onSelectPipeline,
}: MobilePipelineListProps) {
  const { conversations } = useConversationStore();
  const { openNewPipelineModal } = useLayoutStore();
  const { haptic } = useHaptics();
  const { progress, scrollRef, onScroll } = useCollapsibleHeader();
  const [activeFilter, setActiveFilter] = useState<FilterTab>("all");
  const [loaded, setLoaded] = useState(false);
  const pullRef = useRef<HTMLDivElement>(null);

  // Pull to refresh
  usePullToRefresh(pullRef, () => {
    haptic("light");
    return Promise.resolve();
  });

  // Simulate initial load for skeleton
  useState(() => { setTimeout(() => setLoaded(true), 400); });

  // Match pipeline runs to conversations
  const pipelines = useMemo(() => {
    return pipelineRuns.map((run) => {
      const conv = Object.values(conversations).find((c) => c.pipelineId === run.id);
      return { run, conversationId: conv?.id };
    });
  }, [pipelineRuns, conversations]);

  // Apply filter
  const filtered = useMemo(() => {
    switch (activeFilter) {
      case "active":
        return pipelines.filter(
          (p) => p.run.status === "running" || p.run.status === "paused" || p.run.status === "pending",
        );
      case "approval":
        return pipelines.filter((p) => p.run.status === "awaiting_approval");
      case "completed":
        return pipelines.filter(
          (p) => p.run.status === "completed" || p.run.status === "failed",
        );
      default:
        return pipelines;
    }
  }, [pipelines, activeFilter]);

  // Count for approval badge
  const approvalCount = pipelines.filter((p) => p.run.status === "awaiting_approval").length;

  const handleFilterChange = useCallback((key: FilterTab) => {
    haptic("light");
    setActiveFilter(key);
  }, [haptic]);

  const handleSelectPipeline = useCallback((conversationId: string) => {
    haptic("light");
    onSelectPipeline(conversationId);
  }, [haptic, onSelectPipeline]);

  return (
    <div className="flex flex-col h-full">
      {/* Header — iOS large title style */}
      <div className="flex items-center justify-between px-4 pt-[env(safe-area-inset-top)] shrink-0">
        <div className="pt-3 pb-2">
          <h1
            className="large-title text-white font-bold transition-all"
            style={{ fontSize: `${34 - progress * 17}px` }}
          >
            Pipelines
          </h1>
          <StaleIndicator cacheKey="pipelines" />
        </div>
        <button
          onClick={() => { haptic("medium"); openNewPipelineModal(); }}
          aria-label="New pipeline"
          className="p-2 text-[var(--forge-accent)]"
        >
          <Plus className="w-5 h-5" />
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 px-4 pb-2 overflow-x-auto shrink-0" role="tablist" aria-label="Pipeline filters">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleFilterChange(tab.key)}
            role="tab"
            aria-selected={activeFilter === tab.key}
            aria-label={`${tab.label}${tab.key === "approval" && approvalCount > 0 ? `, ${approvalCount} pending` : ""}`}
            className={cn(
              "relative px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors",
              activeFilter === tab.key
                ? "bg-[var(--forge-accent)] text-white"
                : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] active:bg-[var(--forge-border)]",
            )}
          >
            {tab.label}
            {tab.key === "approval" && approvalCount > 0 && (
              <span className="ml-1 px-1 py-px rounded-full bg-white/20 text-[10px]">
                {approvalCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Pipeline list */}
      {!loaded ? (
        <PipelineListSkeleton />
      ) : (
        <div ref={(el) => { (scrollRef as React.MutableRefObject<HTMLDivElement | null>).current = el; pullRef.current = el; }} className="flex-1 overflow-y-auto" onScroll={onScroll} role="list" aria-label="Pipelines">
          {filtered.length > 0 ? (
            <div className="px-4 pb-4 space-y-3">
              {filtered.map((p) => (
                <PipelineCard
                  key={p.run.id}
                  run={p.run}
                  onSelect={() => p.conversationId && handleSelectPipeline(p.conversationId)}
                />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 px-8">
              <Zap className="w-10 h-10 text-[var(--forge-accent)] opacity-40 mb-3" />
              <p className="text-sm text-[var(--forge-text-muted)] text-center">
                {activeFilter === "all"
                  ? "No pipelines yet. Tap + to create one."
                  : `No ${activeFilter === "approval" ? "pending approvals" : activeFilter} pipelines.`}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Pipeline Card ──────────────────────────────────

function PipelineCard({
  run,
  onSelect,
}: {
  run: PipelineRun;
  onSelect: () => void;
}) {
  const config = STATUS_CONFIG[run.status];
  const completedSteps = run.steps.filter((s) => s.status === "completed").length;
  const progressPct = run.steps.length > 0 ? (completedSteps / run.steps.length) * 100 : 0;

  return (
    <button
      onClick={onSelect}
      role="listitem"
      aria-label={`Pipeline: ${run.name}, ${config.label}`}
      className="w-full rounded-xl bg-[var(--forge-sidebar)] border border-[var(--forge-border)] p-4 text-left active:bg-[var(--forge-hover)] transition-colors"
    >
      {/* Title + status */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium text-white line-clamp-2">{run.name}</h3>
        </div>
        <span className={cn("text-[11px] font-medium px-2 py-0.5 rounded-full shrink-0", config.bg, config.color)}>
          {config.emoji} {config.label}
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-[var(--forge-hover)] overflow-hidden mb-2.5">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            run.status === "failed" ? "bg-[var(--forge-error)]" : "bg-[var(--forge-accent)]",
          )}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Stage dots — compact representation */}
      <div className="flex items-center gap-1 mb-2.5">
        {run.steps.map((step) => {
          const agentInfo = AGENT_REGISTRY[step.agentRole];
          return (
            <div
              key={step.id}
              className="relative group"
              title={`${agentInfo.displayName}: ${step.status}`}
            >
              <div className={cn("w-5 h-5 rounded-full flex items-center justify-center text-[10px]", STEP_DOT_COLOR[step.status])}>
                {step.status === "running" ? (
                  <span className="animate-pulse">{agentInfo.emoji}</span>
                ) : (
                  <span className={step.status === "pending" ? "opacity-40" : ""}>{agentInfo.emoji}</span>
                )}
              </div>
            </div>
          );
        })}
        <span className="text-[11px] text-[var(--forge-text-muted)] ml-1">
          {completedSteps}/{run.steps.length}
        </span>
      </div>

      {/* Bottom metadata: time + cost */}
      <div className="flex items-center gap-4 text-[11px] text-[var(--forge-text-muted)]">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {formatElapsed(run.startedAt, run.completedAt)}
        </span>
        {run.cost && (
          <span className="flex items-center gap-1">
            <DollarSign className="w-3 h-3" />
            ${run.cost.total.toFixed(2)}
            {run.cost.budget && (
              <span className="text-[var(--forge-text-muted)]/60">
                / ${run.cost.budget.toFixed(0)}
              </span>
            )}
          </span>
        )}
      </div>
    </button>
  );
}

// ─── Helpers ─────────────────────────────────────────

function formatElapsed(startedAt: string, completedAt?: string): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const diffMs = end - start;

  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours < 24) return `${hours}h ${remainingMinutes}m`;

  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}
