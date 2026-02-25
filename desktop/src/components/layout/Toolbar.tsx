import {
  PanelRightClose,
  PanelRightOpen,
  Search,
  MoreHorizontal,
} from "lucide-react";
import { useLayoutStore } from "@/stores/layoutStore";
import { useConversationStore } from "@/stores/conversationStore";
import { CostTracker } from "@/components/pipeline/CostTracker";
import type { PipelineRun } from "@/types/pipeline";
import type { StepStatus } from "@/types/pipeline";
import { cn } from "@/lib/utils";

const STATUS_ICON: Record<StepStatus, string> = {
  completed: "\u2705",
  running: "\u{1F504}",
  pending: "\u23F3",
  failed: "\u274C",
  skipped: "\u23ED\uFE0F",
};

interface ToolbarProps {
  pipelineRuns: PipelineRun[];
}

export function Toolbar({ pipelineRuns }: ToolbarProps) {
  const { detailPanelOpen, toggleDetailPanel, toggleQuickSwitcher } =
    useLayoutStore();
  const { activeConversationId, conversations } = useConversationStore();

  const active = activeConversationId ? conversations[activeConversationId] : undefined;
  const pipelineRun = active?.pipelineId
    ? pipelineRuns.find((r) => r.id === active.pipelineId)
    : undefined;

  const participantCount = active?.participants.length ?? 0;

  return (
    <div className="flex items-center h-full px-4 gap-3">
      {/* Left: conversation info */}
      <div className="flex items-center gap-2 min-w-0 shrink-0">
        {active ? (
          <>
            <h1 className="font-semibold text-white truncate text-[15px]">
              {active.type === "pipeline" ? "# " : ""}
              {active.title}
            </h1>
            {active.type === "pipeline" && (
              <span className="text-xs text-[var(--forge-text-muted)] shrink-0">
                {participantCount} members
              </span>
            )}
            {active.type === "agent_dm" && (
              <span className="text-xs text-[var(--forge-text-muted)] shrink-0">
                Direct Message
              </span>
            )}
          </>
        ) : (
          <h1 className="font-semibold text-[var(--forge-text-muted)] text-[15px]">
            Forge
          </h1>
        )}
      </div>

      {/* Center: pipeline progress bar */}
      {pipelineRun && (
        <div className="flex-1 flex items-center justify-center gap-1 min-w-0 overflow-x-auto px-2">
          {pipelineRun.steps.map((step, i) => (
            <span key={step.id} className="flex items-center gap-0.5 shrink-0">
              <span
                className={cn(
                  "text-xs px-1.5 py-0.5 rounded font-medium",
                  step.status === "running" &&
                    "bg-[var(--forge-accent)]/20 text-[var(--forge-accent)]",
                  step.status === "completed" &&
                    "text-[var(--forge-success)]",
                  step.status === "failed" &&
                    "text-[var(--forge-error)]",
                  step.status === "pending" &&
                    "text-[var(--forge-text-muted)]",
                  step.status === "skipped" &&
                    "text-[var(--forge-text-muted)] line-through"
                )}
              >
                {step.name} {STATUS_ICON[step.status]}
              </span>
              {i < pipelineRun.steps.length - 1 && (
                <span className="text-[var(--forge-text-muted)] text-xs mx-0.5">
                  →
                </span>
              )}
            </span>
          ))}
        </div>
      )}

      {!pipelineRun && <div className="flex-1" />}

      {/* Right: actions */}
      <div className="flex items-center gap-1.5 shrink-0">
        {/* Cost tracker pill for pipeline conversations */}
        {pipelineRun?.cost && (
          <CostTracker cost={pipelineRun.cost} compact />
        )}

        <button
          onClick={toggleQuickSwitcher}
          className="p-1.5 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
          title="Search (Cmd+K)"
        >
          <Search className="w-4 h-4" />
        </button>

        {active?.type === "pipeline" && (
          <button
            className="p-1.5 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
            title="Pipeline settings"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>
        )}

        <button
          onClick={toggleDetailPanel}
          className={cn(
            "p-1.5 rounded hover:bg-[var(--forge-hover)] transition-colors",
            detailPanelOpen
              ? "text-[var(--forge-accent)]"
              : "text-[var(--forge-text-muted)] hover:text-white"
          )}
          title="Toggle detail panel (Cmd+.)"
        >
          {detailPanelOpen ? (
            <PanelRightClose className="w-4 h-4" />
          ) : (
            <PanelRightOpen className="w-4 h-4" />
          )}
        </button>
      </div>
    </div>
  );
}
