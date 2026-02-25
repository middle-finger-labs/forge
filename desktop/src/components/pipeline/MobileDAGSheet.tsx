import { useState, useRef, useCallback } from "react";
import { AGENT_REGISTRY } from "@/types/agent";
import type { PipelineRun, PipelineStep, StepStatus } from "@/types/pipeline";
import { X, Clock, DollarSign, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status config ──────────────────────────────────

const STATUS_DOT: Record<StepStatus, string> = {
  completed: "bg-[var(--forge-success)]",
  running:   "bg-[var(--forge-accent)]",
  pending:   "bg-[var(--forge-text-muted)]/30",
  failed:    "bg-[var(--forge-error)]",
  skipped:   "bg-[var(--forge-text-muted)]/20",
};

const STATUS_TEXT_COLOR: Record<StepStatus, string> = {
  completed: "text-[var(--forge-success)]",
  running:   "text-[var(--forge-accent)]",
  pending:   "text-[var(--forge-text-muted)]",
  failed:    "text-[var(--forge-error)]",
  skipped:   "text-[var(--forge-text-muted)]",
};

const STATUS_LABEL: Record<StepStatus, string> = {
  completed: "Complete",
  running:   "Running",
  pending:   "Pending",
  failed:    "Failed",
  skipped:   "Skipped",
};

// ─── Props ──────────────────────────────────────────

interface MobileDAGSheetProps {
  run: PipelineRun;
  onClose: () => void;
  onScrollToAgent?: (stepId: string) => void;
}

// ─── Component ──────────────────────────────────────

export function MobileDAGSheet({
  run,
  onClose,
  onScrollToAgent,
}: MobileDAGSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const [dragY, setDragY] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const dragStartY = useRef(0);

  const completedSteps = run.steps.filter((s) => s.status === "completed").length;
  const progressPct = run.steps.length > 0 ? (completedSteps / run.steps.length) * 100 : 0;

  // ── Drag to dismiss / expand ────────────────────

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    dragStartY.current = e.touches[0].clientY;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const dy = e.touches[0].clientY - dragStartY.current;
    // Swipe down → dismiss, swipe up → expand
    setDragY(dy);
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (dragY > 100) {
      onClose();
    } else if (dragY < -60 && !expanded) {
      setExpanded(true);
    } else if (dragY > 60 && expanded) {
      setExpanded(false);
    }
    setDragY(0);
  }, [dragY, expanded, onClose]);

  // ── Tap a step ──────────────────────────────────

  const handleStepTap = useCallback(
    (step: PipelineStep) => {
      onScrollToAgent?.(step.id);
      onClose();
    },
    [onScrollToAgent, onClose],
  );

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
        style={{ opacity: Math.max(0, 1 - Math.max(0, dragY) / 300) }}
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        className={cn(
          "fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-[var(--forge-bg)] flex flex-col transition-[max-height] duration-300",
          expanded ? "max-h-[90vh]" : "max-h-[55vh]",
        )}
        style={{
          transform: `translateY(${Math.max(0, dragY)}px)`,
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Drag handle */}
        <div className="flex justify-center py-2 shrink-0">
          <div className="w-10 h-1 rounded-full bg-[var(--forge-text-muted)]/30" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-4 pb-3 border-b border-[var(--forge-border)] shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-white truncate">
              {run.name}
            </h3>
            <div className="flex items-center gap-3 mt-0.5 text-xs text-[var(--forge-text-muted)]">
              <span>{completedSteps}/{run.steps.length} stages</span>
              {run.cost && (
                <span className="flex items-center gap-0.5">
                  <DollarSign className="w-3 h-3" />
                  {run.cost.total.toFixed(2)}
                  {run.cost.budget && (
                    <span className="opacity-60">/ ${run.cost.budget.toFixed(0)}</span>
                  )}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Progress bar */}
        <div className="px-4 pt-3 pb-1 shrink-0">
          <div className="h-1.5 rounded-full bg-[var(--forge-hover)] overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                run.status === "failed" ? "bg-[var(--forge-error)]" : "bg-[var(--forge-accent)]",
              )}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Stage list (vertical DAG) */}
        <div className="flex-1 overflow-y-auto px-4 pt-2 pb-4">
          {run.steps.map((step, i) => {
            const agentInfo = AGENT_REGISTRY[step.agentRole];
            const isLast = i === run.steps.length - 1;
            const duration = formatStepDuration(step);

            return (
              <button
                key={step.id}
                onClick={() => handleStepTap(step)}
                className="flex gap-3 w-full text-left active:bg-[var(--forge-hover)] rounded-lg transition-colors -mx-1 px-1"
              >
                {/* Timeline connector */}
                <div className="flex flex-col items-center shrink-0 pt-1">
                  <div
                    className={cn(
                      "w-8 h-8 rounded-full flex items-center justify-center text-sm",
                      STATUS_DOT[step.status],
                      step.status === "running" && "animate-pulse",
                    )}
                  >
                    {agentInfo.emoji}
                  </div>
                  {!isLast && (
                    <div
                      className={cn(
                        "w-0.5 flex-1 min-h-[16px]",
                        step.status === "completed"
                          ? "bg-[var(--forge-success)]/30"
                          : "bg-[var(--forge-border)]",
                      )}
                    />
                  )}
                </div>

                {/* Step details */}
                <div className="flex-1 min-w-0 pb-4 pt-0.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-white truncate">
                      {agentInfo.displayName}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      <span
                        className={cn(
                          "text-[11px] font-medium",
                          STATUS_TEXT_COLOR[step.status],
                        )}
                      >
                        {STATUS_LABEL[step.status]}
                      </span>
                      <ChevronRight className="w-3 h-3 text-[var(--forge-text-muted)]" />
                    </div>
                  </div>

                  {/* Duration + cost */}
                  <div className="flex items-center gap-3 mt-0.5 text-[11px] text-[var(--forge-text-muted)]">
                    {duration && (
                      <span className="flex items-center gap-0.5">
                        <Clock className="w-3 h-3" />
                        {duration}
                      </span>
                    )}
                    {step.cost != null && (
                      <span className="flex items-center gap-0.5">
                        <DollarSign className="w-3 h-3" />
                        ${step.cost.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}

// ─── Helpers ─────────────────────────────────────────

function formatStepDuration(step: PipelineStep): string | null {
  if (!step.startedAt) return null;

  const start = new Date(step.startedAt).getTime();
  const end = step.completedAt ? new Date(step.completedAt).getTime() : Date.now();
  const diffMs = end - start;

  if (diffMs < 0) return null;

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
