import { cn } from "@/lib/utils";

// ─── Base skeleton ──────────────────────────────────

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-[var(--forge-hover)]",
        className,
      )}
      role="status"
      aria-label="Loading"
    />
  );
}

// ─── Conversation list skeleton ─────────────────────

export function ConversationListSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="px-4 space-y-1 pt-2" role="status" aria-label="Loading conversations">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-3 rounded-xl">
          <Skeleton className="w-10 h-10 rounded-xl shrink-0" />
          <div className="flex-1 min-w-0 space-y-2">
            <Skeleton className="h-3.5 w-3/5 rounded" />
            <Skeleton className="h-3 w-4/5 rounded" />
          </div>
          <Skeleton className="h-3 w-8 rounded shrink-0" />
        </div>
      ))}
    </div>
  );
}

// ─── Pipeline list skeleton ─────────────────────────

export function PipelineListSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="px-4 space-y-3 pt-2" role="status" aria-label="Loading pipelines">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="rounded-xl bg-[var(--forge-sidebar)] border border-[var(--forge-border)] p-4"
        >
          <div className="flex items-start justify-between gap-2 mb-3">
            <Skeleton className="h-4 w-2/3 rounded" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <Skeleton className="h-1.5 w-full rounded-full mb-3" />
          <div className="flex items-center gap-1.5 mb-3">
            {Array.from({ length: 5 }, (_, j) => (
              <Skeleton key={j} className="w-5 h-5 rounded-full" />
            ))}
          </div>
          <div className="flex items-center gap-4">
            <Skeleton className="h-3 w-12 rounded" />
            <Skeleton className="h-3 w-14 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Message list skeleton ──────────────────────────

export function MessageListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="p-4 space-y-5" role="status" aria-label="Loading messages">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="w-8 h-8 rounded-lg shrink-0" />
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-3.5 w-20 rounded" />
              <Skeleton className="h-2.5 w-10 rounded" />
            </div>
            <Skeleton className="h-3 w-full rounded" />
            <Skeleton className="h-3 w-3/4 rounded" />
            {i % 2 === 0 && (
              <Skeleton className="h-24 w-full rounded-lg mt-1" />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Approval queue skeleton ────────────────────────

export function ApprovalQueueSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="px-4 space-y-3 pt-2" role="status" aria-label="Loading approvals">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="rounded-xl bg-[var(--forge-sidebar)] border border-[var(--forge-border)] p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <Skeleton className="h-3.5 w-3.5 rounded" />
            <Skeleton className="h-3 w-24 rounded" />
          </div>
          <Skeleton className="h-4 w-3/5 rounded mb-2" />
          <Skeleton className="h-3 w-full rounded mb-1" />
          <Skeleton className="h-3 w-4/5 rounded mb-3" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-10 flex-1 rounded-lg" />
            <Skeleton className="h-10 flex-1 rounded-lg" />
            <Skeleton className="h-10 w-10 rounded-lg" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Settings skeleton ──────────────────────────────

export function SettingsSkeleton() {
  return (
    <div className="px-4 space-y-4 pt-4" role="status" aria-label="Loading settings">
      {/* User card */}
      <div className="p-4 rounded-xl bg-[var(--forge-sidebar)]">
        <div className="flex items-center gap-3">
          <Skeleton className="w-10 h-10 rounded-full" />
          <div className="space-y-2 flex-1">
            <Skeleton className="h-3.5 w-24 rounded" />
            <Skeleton className="h-3 w-32 rounded" />
          </div>
        </div>
      </div>
      {/* Settings groups */}
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i}>
          <Skeleton className="h-3 w-20 rounded mb-2 mx-4" />
          <div className="rounded-xl bg-[var(--forge-sidebar)] overflow-hidden">
            {Array.from({ length: 3 }, (_, j) => (
              <div key={j} className="flex items-center gap-3 px-4 py-3">
                <Skeleton className="w-4 h-4 rounded" />
                <Skeleton className="h-3.5 w-32 rounded flex-1" />
                <Skeleton className="w-5 h-5 rounded-full" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
