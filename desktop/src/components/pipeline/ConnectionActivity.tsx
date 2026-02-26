import { useState, useEffect } from "react";
import { Loader2, CheckCircle2, XCircle, Plug } from "lucide-react";
import { useMCPConnectionStore } from "@/stores/mcpConnectionStore";
import type { ConnectionToolCall, ServiceType } from "@/types/connection";
import { SERVICE_INFO } from "@/types/connection";

interface ConnectionActivityProps {
  pipelineId: string;
}

interface GroupedCalls {
  service: ServiceType;
  displayName: string;
  calls: ConnectionToolCall[];
}

export function ConnectionActivity({ pipelineId }: ConnectionActivityProps) {
  const { getPipelineActivity } = useMCPConnectionStore();
  const [calls, setCalls] = useState<ConnectionToolCall[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!pipelineId) return;
    setLoading(true);
    getPipelineActivity(pipelineId)
      .then((data) => setCalls(data))
      .catch(() => setCalls([]))
      .finally(() => setLoading(false));
  }, [pipelineId, getPipelineActivity]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-4 h-4 animate-spin" style={{ color: "var(--forge-text-muted)" }} />
      </div>
    );
  }

  if (calls.length === 0) {
    return (
      <div className="text-center py-8">
        <Plug className="w-6 h-6 mx-auto mb-2" style={{ color: "var(--forge-text-muted)" }} />
        <div className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
          No connection activity for this pipeline
        </div>
      </div>
    );
  }

  // Group calls by service + display_name
  const groups: GroupedCalls[] = [];
  const groupMap = new Map<string, GroupedCalls>();
  for (const call of calls) {
    const key = `${call.service}:${call.display_name}`;
    let group = groupMap.get(key);
    if (!group) {
      group = { service: call.service, displayName: call.display_name, calls: [] };
      groupMap.set(key, group);
      groups.push(group);
    }
    group.calls.push(call);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium" style={{ color: "var(--forge-text-muted)" }}>
          Connection Activity
        </span>
        <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
          {calls.length} call{calls.length !== 1 ? "s" : ""}
        </span>
      </div>

      {groups.map((group) => {
        const info = SERVICE_INFO[group.service] ?? { emoji: "\u{1F50C}", displayName: group.service };
        const successCount = group.calls.filter((c) => c.success).length;
        const failCount = group.calls.length - successCount;

        return (
          <div
            key={`${group.service}:${group.displayName}`}
            className="rounded-lg overflow-hidden"
            style={{ border: "1px solid var(--forge-border)" }}
          >
            {/* Group header */}
            <div
              className="flex items-center justify-between px-3 py-2"
              style={{ background: "var(--forge-hover)" }}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm">{info.emoji}</span>
                <span className="text-xs font-medium" style={{ color: "var(--forge-text)" }}>
                  {group.displayName}
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs" style={{ color: "var(--forge-text-muted)" }}>
                {successCount > 0 && (
                  <span className="flex items-center gap-0.5" style={{ color: "var(--forge-success)" }}>
                    <CheckCircle2 className="w-3 h-3" /> {successCount}
                  </span>
                )}
                {failCount > 0 && (
                  <span className="flex items-center gap-0.5" style={{ color: "var(--forge-error)" }}>
                    <XCircle className="w-3 h-3" /> {failCount}
                  </span>
                )}
              </div>
            </div>

            {/* Individual calls */}
            {group.calls.map((call, i) => (
              <ToolCallRow key={call.id} call={call} showBorder={i > 0} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function ToolCallRow({ call, showBorder }: { call: ConnectionToolCall; showBorder: boolean }) {
  const time = new Date(call.created_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div
      className="flex items-start gap-2 px-3 py-2"
      style={{
        background: "var(--forge-channel)",
        borderTop: showBorder ? "1px solid var(--forge-border)" : undefined,
      }}
    >
      {call.success ? (
        <CheckCircle2
          className="w-3 h-3 mt-0.5 shrink-0"
          style={{ color: "var(--forge-success)" }}
        />
      ) : (
        <XCircle
          className="w-3 h-3 mt-0.5 shrink-0"
          style={{ color: "var(--forge-error)" }}
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono" style={{ color: "var(--forge-text)" }}>
            {call.tool_name}
          </span>
          {call.agent_role && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{
                background: "var(--forge-hover)",
                color: "var(--forge-text-muted)",
              }}
            >
              {call.agent_role}
            </span>
          )}
        </div>
        {call.result_summary && (
          <div className="text-xs mt-0.5 truncate" style={{ color: "var(--forge-text-muted)" }}>
            {call.result_summary}
          </div>
        )}
        {call.error_message && (
          <div className="text-xs mt-0.5 truncate" style={{ color: "var(--forge-error)" }}>
            {call.error_message}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {call.duration_ms != null && (
          <span className="text-[10px]" style={{ color: "var(--forge-text-muted)" }}>
            {call.duration_ms}ms
          </span>
        )}
        <span className="text-[10px]" style={{ color: "var(--forge-text-muted)" }}>
          {time}
        </span>
      </div>
    </div>
  );
}
