import { useOfflineStore } from "@/stores/offlineStore";
import { Wifi, WifiOff, Loader2, CloudOff } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Component ──────────────────────────────────────

export function MobileConnectionBar() {
  const { networkStatus, actionQueue } = useOfflineStore();
  const queuedCount = actionQueue.length;

  // Don't render when online and no queued actions
  if (networkStatus === "online" && queuedCount === 0) return null;

  const config = STATUS_CONFIG[networkStatus];

  return (
    <div
      className={cn(
        "flex items-center justify-center gap-1.5 px-3 py-1 text-xs font-medium shrink-0 transition-colors",
        config.bg,
        config.text,
      )}
    >
      {config.icon}
      <span>{config.label}</span>
      {queuedCount > 0 && (
        <span className="ml-1 opacity-80">
          ({queuedCount} queued)
        </span>
      )}
    </div>
  );
}

// ─── Status config ──────────────────────────────────

const STATUS_CONFIG = {
  online: {
    label: "Back online — syncing",
    bg: "bg-[var(--forge-success)]",
    text: "text-white",
    icon: <Wifi className="w-3 h-3" />,
  },
  reconnecting: {
    label: "Reconnecting...",
    bg: "bg-amber-500",
    text: "text-white",
    icon: <Loader2 className="w-3 h-3 animate-spin" />,
  },
  offline: {
    label: "Offline — showing cached data",
    bg: "bg-[var(--forge-error)]",
    text: "text-white",
    icon: <WifiOff className="w-3 h-3" />,
  },
} as const;

// ─── Stale data indicator ───────────────────────────

interface StaleIndicatorProps {
  cacheKey: "conversations" | "pipelines" | "agents";
}

export function StaleIndicator({ cacheKey }: StaleIndicatorProps) {
  const { staleSince } = useOfflineStore();
  const label = staleSince(cacheKey);

  if (!label) return null;

  return (
    <div className="flex items-center gap-1 text-[10px] text-[var(--forge-text-muted)] opacity-70">
      <CloudOff className="w-3 h-3" />
      <span>{label}</span>
    </div>
  );
}
