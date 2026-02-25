import { useMemo } from "react";
import { Loader2, Zap } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import type { PipelineRun } from "@/types/pipeline";

interface StatusBarProps {
  pipelineRuns: PipelineRun[];
}

export function StatusBar({ pipelineRuns }: StatusBarProps) {
  const { connectionStatus, serverUrl, user, org } = useConnectionStore();

  const activePipelines = useMemo(
    () => pipelineRuns.filter((r) => r.status === "running"),
    [pipelineRuns]
  );

  const totalCostToday = useMemo(() => {
    return pipelineRuns.reduce((sum, r) => sum + (r.cost?.total ?? 0), 0);
  }, [pipelineRuns]);

  // Connection display
  const hostname = serverUrl
    ? serverUrl.replace(/^https?:\/\//, "").replace(/\/.*$/, "")
    : "not configured";

  return (
    <div
      className="flex items-center justify-between px-3 h-6 text-[11px] select-none shrink-0"
      style={{
        background: "var(--forge-sidebar)",
        borderTop: "1px solid var(--forge-border)",
        color: "var(--forge-text-muted)",
      }}
    >
      {/* Left: Connection status */}
      <div className="flex items-center gap-1.5 min-w-0">
        <ConnectionIndicator status={connectionStatus} />
        <span className="truncate">
          {connectionStatus === "authenticated"
            ? `Connected to ${hostname}`
            : connectionStatus === "connected"
              ? `Connected to ${hostname}`
              : connectionStatus === "connecting"
                ? `Connecting to ${hostname}...`
                : connectionStatus === "error"
                  ? "Connection error"
                  : `Disconnected`}
        </span>
      </div>

      {/* Center: Active pipelines */}
      <div className="flex items-center gap-1.5">
        {activePipelines.length > 0 ? (
          <>
            <Zap className="w-3 h-3" style={{ color: "var(--forge-accent)" }} />
            <span>
              {activePipelines.length} pipeline{activePipelines.length !== 1 ? "s" : ""} running
            </span>
          </>
        ) : (
          <span>No active pipelines</span>
        )}
      </div>

      {/* Right: Cost, name, org */}
      <div className="flex items-center gap-3 min-w-0">
        {totalCostToday > 0 && (
          <span>
            ${totalCostToday.toFixed(2)} today
          </span>
        )}
        {user && (
          <span className="truncate">
            {user.name}
          </span>
        )}
        {org && (
          <span className="truncate" style={{ opacity: 0.7 }}>
            {org.name}
          </span>
        )}
      </div>
    </div>
  );
}

function ConnectionIndicator({
  status,
}: {
  status: ReturnType<typeof useConnectionStore.getState>["connectionStatus"];
}) {
  if (status === "connecting") {
    return <Loader2 className="w-3 h-3 animate-spin" style={{ color: "var(--forge-warning)" }} />;
  }

  if (status === "authenticated" || status === "connected") {
    return (
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: "var(--forge-success)" }}
      />
    );
  }

  if (status === "error") {
    return (
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: "var(--forge-error)" }}
      />
    );
  }

  // disconnected / unconfigured
  return (
    <span
      className="w-2 h-2 rounded-full shrink-0"
      style={{ background: "var(--forge-text-muted)", opacity: 0.5 }}
    />
  );
}
