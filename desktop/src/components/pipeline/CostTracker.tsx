import { useState } from "react";
import { DollarSign, ChevronDown, ChevronUp } from "lucide-react";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import type { PipelineCost } from "@/types/pipeline";
import { cn } from "@/lib/utils";

// ─── Props ───────────────────────────────────────────

interface CostTrackerProps {
  cost: PipelineCost;
  /** Compact inline mode for toolbar */
  compact?: boolean;
}

// ─── Budget color thresholds ─────────────────────────

function getBudgetLevel(
  total: number,
  budget?: number
): "ok" | "warning" | "danger" | "none" {
  if (budget == null || budget <= 0) return "none";
  const pct = total / budget;
  if (pct >= 0.8) return "danger";
  if (pct >= 0.5) return "warning";
  return "ok";
}

const BUDGET_COLORS = {
  ok: {
    text: "text-[var(--forge-success)]",
    bg: "bg-[var(--forge-success)]",
    border: "border-[var(--forge-success)]/30",
  },
  warning: {
    text: "text-[var(--forge-warning)]",
    bg: "bg-[var(--forge-warning)]",
    border: "border-[var(--forge-warning)]/30",
  },
  danger: {
    text: "text-[var(--forge-error)]",
    bg: "bg-[var(--forge-error)]",
    border: "border-[var(--forge-error)]/30",
  },
  none: {
    text: "text-[var(--forge-text-muted)]",
    bg: "bg-[var(--forge-text-muted)]",
    border: "border-[var(--forge-border)]",
  },
};

// ─── CostTracker ─────────────────────────────────────

export function CostTracker({ cost, compact = false }: CostTrackerProps) {
  const [expanded, setExpanded] = useState(false);
  const level = getBudgetLevel(cost.total, cost.budget);
  const colors = BUDGET_COLORS[level];

  const remaining =
    cost.budget != null ? Math.max(0, cost.budget - cost.total) : null;
  const pct =
    cost.budget != null && cost.budget > 0
      ? Math.min(100, (cost.total / cost.budget) * 100)
      : null;

  const agentEntries = Object.entries(cost.perAgent) as [AgentRole, number][];
  agentEntries.sort((a, b) => b[1] - a[1]);

  // ─── Compact mode (toolbar pill) ─────────────────
  if (compact) {
    return (
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "relative flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
          "border",
          colors.border,
          "hover:bg-[var(--forge-hover)]"
        )}
        title="Pipeline cost"
      >
        <DollarSign className={cn("w-3 h-3", colors.text)} />
        <span className={cn("font-mono", colors.text)}>
          {cost.total.toFixed(2)}
        </span>
        {cost.budget != null && (
          <span className="text-[var(--forge-text-muted)] font-normal">
            / ${cost.budget.toFixed(2)}
          </span>
        )}
        {expanded ? (
          <ChevronUp className="w-3 h-3 text-[var(--forge-text-muted)]" />
        ) : (
          <ChevronDown className="w-3 h-3 text-[var(--forge-text-muted)]" />
        )}

        {/* Expanded dropdown */}
        {expanded && (
          <div
            className="absolute top-full right-0 mt-1 w-56 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl z-50"
            onClick={(e) => e.stopPropagation()}
          >
            <CostBreakdown
              cost={cost}
              level={level}
              remaining={remaining}
              pct={pct}
              agentEntries={agentEntries}
            />
          </div>
        )}
      </button>
    );
  }

  // ─── Full mode (detail panel) ─────────────────────
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
        Cost Tracker
      </h3>
      <CostBreakdown
        cost={cost}
        level={level}
        remaining={remaining}
        pct={pct}
        agentEntries={agentEntries}
      />
    </div>
  );
}

// ─── Cost breakdown panel ────────────────────────────

function CostBreakdown({
  cost,
  level,
  remaining,
  pct,
  agentEntries,
}: {
  cost: PipelineCost;
  level: "ok" | "warning" | "danger" | "none";
  remaining: number | null;
  pct: number | null;
  agentEntries: [AgentRole, number][];
}) {
  const colors = BUDGET_COLORS[level];

  return (
    <div className="p-3 space-y-3">
      {/* Total */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--forge-text-muted)]">
          Running cost
        </span>
        <span className={cn("text-sm font-mono font-semibold", colors.text)}>
          ${cost.total.toFixed(4)}
        </span>
      </div>

      {/* Budget bar */}
      {pct != null && cost.budget != null && (
        <div className="space-y-1">
          <div className="h-2 rounded-full bg-[var(--forge-border)] overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                colors.bg
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-[10px] text-[var(--forge-text-muted)]">
            <span>{Math.round(pct)}% of budget</span>
            {remaining != null && (
              <span className="font-mono">${remaining.toFixed(2)} left</span>
            )}
          </div>
        </div>
      )}

      {/* Per-agent breakdown */}
      {agentEntries.length > 0 && (
        <div className="space-y-1.5 pt-2 border-t border-[var(--forge-border)]">
          <span className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
            Per Agent
          </span>
          {agentEntries.map(([role, agentCost]) => {
            const info = AGENT_REGISTRY[role];
            const agentPct =
              cost.total > 0 ? (agentCost / cost.total) * 100 : 0;
            return (
              <div key={role} className="flex items-center gap-2">
                <span className="text-xs shrink-0">{info?.emoji ?? "\u{1F916}"}</span>
                <span className="text-[11px] text-[var(--forge-text)] flex-1 truncate">
                  {info?.displayName ?? role}
                </span>
                <div className="w-12 h-1 rounded-full bg-[var(--forge-border)] overflow-hidden shrink-0">
                  <div
                    className="h-full rounded-full bg-[var(--forge-accent)]"
                    style={{ width: `${agentPct}%` }}
                  />
                </div>
                <span className="text-[10px] font-mono text-[var(--forge-text-muted)] w-12 text-right shrink-0">
                  ${agentCost.toFixed(3)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
