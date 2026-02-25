import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import { cn } from "@/lib/utils";

interface PerAgentData {
  cost: number;
  duration: number;
  firstPass: boolean;
  attempts: number;
  lessonsApplied: number;
}

interface PipelineSummaryData {
  type: "pipeline_summary";
  pipelineId: string;
  totalCost: number;
  totalDuration: number;
  perAgent: Record<string, PerAgentData>;
  lessonsApplied: Array<{ agentRole: string; lesson: string }>;
}

export function PipelineSummaryCard({ data }: { data: PipelineSummaryData }) {
  const [showLessons, setShowLessons] = useState(false);
  const agents = Object.entries(data.perAgent) as [string, PerAgentData][];
  const maxCost = Math.max(...agents.map(([, a]) => a.cost), 0.001);

  return (
    <div
      className="rounded-lg overflow-hidden max-w-lg"
      style={{
        border: "1px solid var(--forge-border)",
        background: "var(--forge-channel)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: "1px solid var(--forge-border)" }}
      >
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" style={{ color: "var(--forge-success)" }} />
          <span className="text-sm font-semibold" style={{ color: "var(--forge-text)" }}>
            Pipeline Complete
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs" style={{ color: "var(--forge-text-muted)" }}>
          <span className="font-mono">${data.totalCost.toFixed(4)}</span>
          <span>{formatDuration(data.totalDuration)}</span>
        </div>
      </div>

      {/* Agent breakdown table */}
      <div className="px-4 py-2">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ color: "var(--forge-text-muted)" }}>
              <th className="text-left font-medium py-1">Agent</th>
              <th className="text-right font-medium py-1 w-16">Cost</th>
              <th className="text-right font-medium py-1 w-14">Time</th>
              <th className="text-right font-medium py-1 w-20">Result</th>
              <th className="text-right font-medium py-1 w-10">#</th>
            </tr>
          </thead>
          <tbody>
            {agents.map(([role, agent]) => {
              const info = AGENT_REGISTRY[role as AgentRole];
              const costPct = (agent.cost / maxCost) * 100;
              return (
                <tr
                  key={role}
                  style={{ borderTop: "1px solid var(--forge-border)" }}
                >
                  <td className="py-1.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm">{info?.emoji ?? "\u{1F916}"}</span>
                      <span style={{ color: "var(--forge-text)" }}>
                        {info?.displayName ?? role}
                      </span>
                    </div>
                  </td>
                  <td className="text-right py-1.5">
                    <div className="flex items-center justify-end gap-1">
                      <div className="w-8 h-1 rounded-full bg-[var(--forge-border)] overflow-hidden">
                        <div
                          className="h-full rounded-full bg-[var(--forge-accent)]"
                          style={{ width: `${costPct}%` }}
                        />
                      </div>
                      <span
                        className="font-mono"
                        style={{ color: "var(--forge-text-muted)" }}
                      >
                        ${agent.cost.toFixed(3)}
                      </span>
                    </div>
                  </td>
                  <td
                    className="text-right font-mono py-1.5"
                    style={{ color: "var(--forge-text-muted)" }}
                  >
                    {formatDuration(agent.duration)}
                  </td>
                  <td className="text-right py-1.5">
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-medium",
                        agent.firstPass
                          ? "bg-[var(--forge-success)]/10 text-[var(--forge-success)]"
                          : "bg-[var(--forge-warning)]/10 text-[var(--forge-warning)]"
                      )}
                    >
                      {agent.firstPass ? "First pass" : "Revised"}
                    </span>
                  </td>
                  <td
                    className="text-right font-mono py-1.5"
                    style={{ color: "var(--forge-text-muted)" }}
                  >
                    {agent.attempts}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Lessons applied (collapsible) */}
      {data.lessonsApplied.length > 0 && (
        <div style={{ borderTop: "1px solid var(--forge-border)" }}>
          <button
            onClick={() => setShowLessons(!showLessons)}
            className="flex items-center gap-2 w-full px-4 py-2 text-xs cursor-pointer"
            style={{ color: "var(--forge-text-muted)" }}
          >
            {showLessons ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
            {data.lessonsApplied.length} lesson
            {data.lessonsApplied.length !== 1 ? "s" : ""} applied
          </button>
          {showLessons && (
            <div className="px-4 pb-3 space-y-1.5">
              {data.lessonsApplied.map((l, i) => {
                const info = AGENT_REGISTRY[l.agentRole as AgentRole];
                return (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span
                      className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium"
                      style={{
                        background: "var(--forge-accent)20",
                        color: "var(--forge-accent)",
                      }}
                    >
                      {info?.displayName ?? l.agentRole}
                    </span>
                    <span style={{ color: "var(--forge-text)" }}>
                      {l.lesson}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${s > 0 ? ` ${s}s` : ""}`;
}
