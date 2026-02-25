import { useState, useRef, useCallback } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { AGENT_REGISTRY } from "@/types/agent";
import type { PipelineRun, StepStatus } from "@/types/pipeline";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status config ──────────────────────────────────

const STATUS_COLOR: Record<StepStatus, string> = {
  completed: "bg-[var(--forge-success)]",
  running: "bg-[var(--forge-accent)]",
  pending: "bg-[var(--forge-text-muted)]/30",
  failed: "bg-[var(--forge-error)]",
  skipped: "bg-[var(--forge-text-muted)]/20",
};

const STATUS_TEXT: Record<StepStatus, string> = {
  completed: "text-[var(--forge-success)]",
  running: "text-[var(--forge-accent)]",
  pending: "text-[var(--forge-text-muted)]",
  failed: "text-[var(--forge-error)]",
  skipped: "text-[var(--forge-text-muted)]",
};

const STATUS_ICON: Record<StepStatus, string> = {
  completed: "\u2705",
  running: "\u{1F504}",
  pending: "\u23F3",
  failed: "\u274C",
  skipped: "\u23ED\uFE0F",
};

// ─── Props ──────────────────────────────────────────

interface MobileBottomSheetProps {
  type: "dag" | "profile";
  conversationId: string;
  pipelineRuns: PipelineRun[];
  onClose: () => void;
}

// ─── Component ──────────────────────────────────────

export function MobileBottomSheet({
  type,
  conversationId,
  pipelineRuns,
  onClose,
}: MobileBottomSheetProps) {
  const { conversations, agents } = useConversationStore();
  const conversation = conversations[conversationId];

  const pipelineRun = conversation?.pipelineId
    ? pipelineRuns.find((r) => r.id === conversation.pipelineId)
    : undefined;

  // Drag to dismiss
  const sheetRef = useRef<HTMLDivElement>(null);
  const [dragY, setDragY] = useState(0);
  const dragStartY = useRef(0);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    dragStartY.current = e.touches[0].clientY;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const dy = e.touches[0].clientY - dragStartY.current;
    if (dy > 0) setDragY(dy); // Only drag downward
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (dragY > 100) {
      onClose();
    }
    setDragY(0);
  }, [dragY, onClose]);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
        style={{ opacity: Math.max(0, 1 - dragY / 300) }}
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-[var(--forge-bg)] max-h-[80vh] flex flex-col"
        style={{
          transform: `translateY(${dragY}px)`,
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
          <h3 className="text-base font-semibold text-white">
            {type === "dag" ? "Pipeline DAG" : "Agent Profile"}
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {type === "dag" && pipelineRun && <DAGView run={pipelineRun} />}
          {type === "dag" && !pipelineRun && (
            <p className="text-sm text-[var(--forge-text-muted)] text-center py-8">
              No pipeline data available
            </p>
          )}
          {type === "profile" && conversation?.agentRole && (
            <AgentProfileView
              agentRole={conversation.agentRole}
              agent={agents[conversation.agentRole]}
            />
          )}
        </div>
      </div>
    </>
  );
}

// ─── DAG View ───────────────────────────────────────

function DAGView({ run }: { run: PipelineRun }) {
  const completedSteps = run.steps.filter((s) => s.status === "completed").length;
  const progressPct = run.steps.length > 0 ? (completedSteps / run.steps.length) * 100 : 0;

  return (
    <div>
      {/* Overview */}
      <div className="mb-4">
        <h4 className="text-sm font-medium text-white mb-1">{run.name}</h4>
        <div className="flex items-center gap-3 text-xs text-[var(--forge-text-muted)]">
          <span>{completedSteps}/{run.steps.length} steps complete</span>
          {run.cost && <span>${run.cost.total.toFixed(2)} spent</span>}
        </div>

        {/* Progress bar */}
        <div className="mt-2 h-2 rounded-full bg-[var(--forge-hover)] overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              run.status === "failed" ? "bg-[var(--forge-error)]" : "bg-[var(--forge-accent)]"
            )}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-0">
        {run.steps.map((step, i) => {
          const agentInfo = AGENT_REGISTRY[step.agentRole];
          const isLast = i === run.steps.length - 1;

          return (
            <div key={step.id} className="flex gap-3">
              {/* Timeline */}
              <div className="flex flex-col items-center shrink-0">
                <div className={cn("w-3 h-3 rounded-full border-2 border-[var(--forge-bg)]", STATUS_COLOR[step.status])} />
                {!isLast && (
                  <div className={cn("w-0.5 flex-1 min-h-[24px]",
                    step.status === "completed" ? "bg-[var(--forge-success)]/30" : "bg-[var(--forge-border)]"
                  )} />
                )}
              </div>

              {/* Step info */}
              <div className="pb-4 min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={cn("text-sm font-medium", STATUS_TEXT[step.status])}>
                    {step.name}
                  </span>
                  <span className="text-xs">{STATUS_ICON[step.status]}</span>
                </div>
                <div className="flex items-center gap-2 mt-0.5 text-xs text-[var(--forge-text-muted)]">
                  <span>{agentInfo.emoji} {agentInfo.displayName}</span>
                  {step.cost != null && <span>${step.cost.toFixed(2)}</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Agent Profile View ─────────────────────────────

function AgentProfileView({
  agentRole,
  agent,
}: {
  agentRole: import("@/types/agent").AgentRole;
  agent?: import("@/types/agent").Agent;
}) {
  const info = AGENT_REGISTRY[agentRole];

  const STATUS_DOT: Record<string, string> = {
    idle: "bg-[var(--forge-success)]",
    working: "bg-[var(--forge-warning)]",
    waiting: "bg-[var(--forge-warning)]",
    error: "bg-[var(--forge-error)]",
    offline: "bg-gray-500",
  };

  const STATUS_LABEL: Record<string, string> = {
    idle: "Online",
    working: "Working",
    waiting: "Waiting for input",
    error: "Error",
    offline: "Offline",
  };

  return (
    <div className="flex flex-col items-center text-center">
      <span className="text-5xl mb-3">{info.emoji}</span>
      <h3 className="text-lg font-semibold text-white">{info.displayName}</h3>

      {agent && (
        <div className="flex items-center gap-2 mt-2 text-sm text-[var(--forge-text-muted)]">
          <span className={cn("w-2.5 h-2.5 rounded-full", STATUS_DOT[agent.status] ?? STATUS_DOT.offline)} />
          <span>{STATUS_LABEL[agent.status] ?? "Offline"}</span>
        </div>
      )}

      {agent?.currentTask && (
        <p className="mt-2 text-xs text-[var(--forge-text-muted)] italic">
          {agent.currentTask}
        </p>
      )}

      <div className="w-full mt-6 text-left">
        <h4 className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
          Role Details
        </h4>
        <div className="space-y-2 text-sm text-[var(--forge-text)]">
          <div className="flex justify-between">
            <span className="text-[var(--forge-text-muted)]">Role ID</span>
            <span className="font-mono text-xs">{agentRole}</span>
          </div>
          {agent?.lastActive && (
            <div className="flex justify-between">
              <span className="text-[var(--forge-text-muted)]">Last active</span>
              <span className="text-xs">
                {new Date(agent.lastActive).toLocaleTimeString()}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
