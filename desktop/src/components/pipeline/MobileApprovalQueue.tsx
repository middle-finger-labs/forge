import { useState, useMemo, useRef, useCallback } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useOfflineStore } from "@/stores/offlineStore";
import { useHaptics } from "@/hooks/useHaptics";
import { AGENT_REGISTRY } from "@/types/agent";
import type { PipelineRun } from "@/types/pipeline";
import type { Message, MessageContent } from "@/types/message";
import {
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  ChevronRight,
  WifiOff,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────

interface ApprovalItem {
  approvalId: string;
  stage: string;
  summary: string;
  pipelineName: string;
  pipelineId: string;
  conversationId: string;
  messageId: string;
  agentRole?: string;
  timestamp: string;
}

// ─── Props ──────────────────────────────────────────

interface MobileApprovalQueueProps {
  pipelineRuns: PipelineRun[];
  onNavigateToConversation: (conversationId: string) => void;
}

// ─── Component ──────────────────────────────────────

export function MobileApprovalQueue({
  pipelineRuns,
  onNavigateToConversation,
}: MobileApprovalQueueProps) {
  const { conversations, messages, setMessages } = useConversationStore();
  const { networkStatus, enqueueApproval } = useOfflineStore();
  const { haptic } = useHaptics();
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());
  const isOffline = networkStatus === "offline";

  // Gather ALL pending approvals across ALL pipelines
  const approvals = useMemo(() => {
    const items: ApprovalItem[] = [];

    for (const conv of Object.values(conversations)) {
      if (conv.type !== "pipeline") continue;

      const convMessages = messages[conv.id] ?? [];
      const pipelineRun = pipelineRuns.find((r) => r.id === conv.pipelineId);

      for (const msg of convMessages) {
        for (const block of msg.content) {
          if (block.type === "approval_request") {
            // Check if already responded
            const hasResponse = convMessages.some(
              (m) =>
                m.createdAt > msg.createdAt &&
                m.content.some(
                  (c) =>
                    c.type === "approval_response" &&
                    msg.content.some(
                      (b) =>
                        b.type === "approval_request" &&
                        b.approvalId === block.approvalId,
                    ),
                ),
            );
            if (hasResponse) continue;

            items.push({
              approvalId: block.approvalId,
              stage: block.stage,
              summary: block.summary,
              pipelineName: pipelineRun?.name ?? conv.title,
              pipelineId: conv.pipelineId ?? "",
              conversationId: conv.id,
              messageId: msg.id,
              agentRole:
                msg.author.type === "agent" ? msg.author.role : undefined,
              timestamp: msg.createdAt,
            });
          }
        }
      }
    }

    // Sort newest first
    items.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    return items;
  }, [conversations, messages, pipelineRuns]);

  // ── Approve / Reject ────────────────────────────

  const handleAction = useCallback(
    async (item: ApprovalItem, approved: boolean) => {
      if (processingIds.has(item.approvalId)) return;

      haptic(approved ? "heavy" : "medium");

      setProcessingIds((prev) => new Set(prev).add(item.approvalId));

      // If offline, queue the approval for later
      if (isOffline) {
        enqueueApproval(
          item.pipelineId,
          item.conversationId,
          item.approvalId,
          item.stage,
          approved,
          approved ? undefined : "Rejected from mobile approval queue",
        );
      }

      // Add approval response message to the conversation (optimistic)
      const convMessages = messages[item.conversationId] ?? [];
      const responseMsg: Message = {
        id: `msg-approval-${item.approvalId}-${Date.now()}`,
        conversationId: item.conversationId,
        author: { type: "user", userId: "me", name: "You" },
        content: [
          {
            type: "approval_response",
            approved,
            comment: approved ? undefined : "Rejected from mobile approval queue",
          } as MessageContent,
        ],
        createdAt: new Date().toISOString(),
      };

      setMessages(item.conversationId, [...convMessages, responseMsg]);

      // Brief delay for visual feedback
      setTimeout(() => {
        setProcessingIds((prev) => {
          const next = new Set(prev);
          next.delete(item.approvalId);
          return next;
        });
      }, 300);
    },
    [processingIds, messages, setMessages, isOffline, enqueueApproval, haptic],
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 pt-[env(safe-area-inset-top)] shrink-0">
        <div className="pt-3 pb-2">
          <h1 className="text-xl font-bold text-white">Approvals</h1>
          <p className="text-xs text-[var(--forge-text-muted)] mt-0.5">
            {approvals.length === 0
              ? "All caught up"
              : `${approvals.length} pending approval${approvals.length !== 1 ? "s" : ""}`}
            {isOffline && approvals.length > 0 && (
              <span className="inline-flex items-center gap-0.5 ml-2 text-[var(--forge-warning)]">
                <WifiOff className="w-3 h-3 inline" />
                Approvals will sync when online
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Approval list */}
      <div className="flex-1 overflow-y-auto">
        {approvals.length > 0 ? (
          <div className="px-4 pb-4 space-y-3 pt-2">
            {approvals.map((item) => (
              <ApprovalCard
                key={item.approvalId}
                item={item}
                processing={processingIds.has(item.approvalId)}
                onApprove={() => handleAction(item, true)}
                onReject={() => handleAction(item, false)}
                onNavigate={() =>
                  onNavigateToConversation(item.conversationId)
                }
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 px-8">
            <CheckCircle2 className="w-10 h-10 text-[var(--forge-success)] opacity-40 mb-3" />
            <p className="text-sm text-[var(--forge-text-muted)] text-center">
              No pending approvals. Your pipelines are running smoothly.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Approval Card ──────────────────────────────────

function ApprovalCard({
  item,
  processing,
  onApprove,
  onReject,
  onNavigate,
}: {
  item: ApprovalItem;
  processing: boolean;
  onApprove: () => void;
  onReject: () => void;
  onNavigate: () => void;
}) {
  const swipeRef = useRef<HTMLDivElement>(null);
  const [swipeX, setSwipeX] = useState(0);
  const startX = useRef(0);
  const startY = useRef(0);
  const isHorizontal = useRef<boolean | null>(null);

  const agentInfo = item.agentRole
    ? AGENT_REGISTRY[item.agentRole as keyof typeof AGENT_REGISTRY]
    : null;

  // ── Swipe to approve ────────────────────────────

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    startX.current = e.touches[0].clientX;
    startY.current = e.touches[0].clientY;
    isHorizontal.current = null;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - startX.current;
    const dy = e.touches[0].clientY - startY.current;

    // Lock to horizontal after first 10px of movement
    if (isHorizontal.current === null && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
      isHorizontal.current = Math.abs(dx) > Math.abs(dy);
    }

    if (isHorizontal.current) {
      // Only allow rightward swipe (approve)
      setSwipeX(Math.max(0, dx));
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (swipeX > 120) {
      // Swipe complete → approve
      onApprove();
    }
    setSwipeX(0);
    isHorizontal.current = null;
  }, [swipeX, onApprove]);

  const swipeProgress = Math.min(swipeX / 120, 1);

  return (
    <div className="relative overflow-hidden rounded-xl">
      {/* Swipe background (green = approve) */}
      <div
        className="absolute inset-0 bg-[var(--forge-success)] flex items-center pl-5 rounded-xl"
        style={{ opacity: swipeProgress * 0.8 }}
      >
        <CheckCircle2 className="w-6 h-6 text-white" />
        <span className="ml-2 text-sm font-semibold text-white">Approve</span>
      </div>

      {/* Card */}
      <div
        ref={swipeRef}
        className={cn(
          "relative rounded-xl bg-[var(--forge-sidebar)] border border-[var(--forge-border)] p-4 transition-transform",
          processing && "opacity-50 pointer-events-none",
        )}
        style={{ transform: `translateX(${swipeX}px)` }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Pipeline name + agent */}
        <div className="flex items-center gap-2 mb-2">
          <Zap className="w-3.5 h-3.5 text-[var(--forge-accent)]" />
          <span className="text-xs font-medium text-[var(--forge-accent)] truncate">
            {item.pipelineName}
          </span>
          <span className="text-[10px] text-[var(--forge-text-muted)]">
            {agentInfo ? `${agentInfo.emoji} ${agentInfo.displayName}` : ""}
          </span>
        </div>

        {/* Stage */}
        <h3 className="text-sm font-medium text-white mb-1">{item.stage}</h3>

        {/* Summary */}
        <p className="text-xs text-[var(--forge-text-muted)] line-clamp-3 mb-3">
          {item.summary}
        </p>

        {/* Timestamp */}
        <div className="flex items-center gap-1 text-[10px] text-[var(--forge-text-muted)] mb-3">
          <Clock className="w-3 h-3" />
          {formatTimeAgo(item.timestamp)}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2" role="group" aria-label={`Actions for ${item.stage}`}>
          <button
            onClick={onApprove}
            aria-label={`Approve ${item.stage}`}
            className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-[var(--forge-success)] text-white text-sm font-medium active:opacity-80 transition-opacity"
          >
            <CheckCircle2 className="w-4 h-4" />
            Approve
          </button>
          <button
            onClick={onReject}
            aria-label={`Reject ${item.stage}`}
            className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-[var(--forge-error)]/10 text-[var(--forge-error)] text-sm font-medium active:opacity-80 transition-opacity"
          >
            <XCircle className="w-4 h-4" />
            Reject
          </button>
          <button
            onClick={onNavigate}
            aria-label="View in pipeline"
            className="p-2.5 rounded-lg bg-[var(--forge-hover)] text-[var(--forge-text-muted)] active:bg-[var(--forge-border)] transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────

function formatTimeAgo(timestamp: string): string {
  const diffMs = Date.now() - new Date(timestamp).getTime();
  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
