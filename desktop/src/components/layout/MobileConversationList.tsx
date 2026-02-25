import { useState, useRef, useMemo, useCallback } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { usePullToRefresh } from "@/hooks/useMobileGestures";
import { useCollapsibleHeader } from "@/hooks/useCollapsibleHeader";
import { useHaptics } from "@/hooks/useHaptics";
import { StaleIndicator } from "./MobileConnectionBar";
import { ConversationListSkeleton } from "@/components/ui/Skeleton";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentStatus } from "@/types/agent";
import type { Conversation } from "@/types/conversation";
import type { MessageContent } from "@/types/message";
import type { PipelineRun, PipelineStatus } from "@/types/pipeline";
import {
  Plus,
  Hash,
  Loader2,
  Pin,
  CheckCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────

interface MobileConversationListProps {
  onSelectConversation: (id: string) => void;
  pipelineRuns: PipelineRun[];
}

// ─── Status styling ─────────────────────────────────

const STATUS_DOT: Record<AgentStatus, string> = {
  idle: "bg-[var(--forge-success)]",
  working: "bg-[var(--forge-warning)]",
  waiting: "bg-[var(--forge-warning)]",
  error: "bg-[var(--forge-error)]",
  offline: "bg-gray-500",
};

const PIPELINE_STATUS_LABEL: Record<PipelineStatus, { text: string; color: string }> = {
  running: { text: "Running", color: "text-[var(--forge-success)]" },
  completed: { text: "Done", color: "text-[var(--forge-success)]" },
  failed: { text: "Failed", color: "text-[var(--forge-error)]" },
  paused: { text: "Paused", color: "text-[var(--forge-warning)]" },
  awaiting_approval: { text: "Needs approval", color: "text-[var(--forge-warning)]" },
  pending: { text: "Pending", color: "text-[var(--forge-text-muted)]" },
};

// ─── Component ──────────────────────────────────────

export function MobileConversationList({
  onSelectConversation,
  pipelineRuns,
}: MobileConversationListProps) {
  const { conversations, messages, agents, markRead } = useConversationStore();
  const { openNewPipelineModal } = useLayoutStore();
  const { haptic } = useHaptics();
  const { progress, collapsed, scrollRef, onScroll } = useCollapsibleHeader();
  const pullRef = useRef<HTMLDivElement>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // Pull to refresh
  usePullToRefresh(pullRef, async () => {
    setRefreshing(true);
    haptic("light");
    // Simulate refresh — in production, this would re-fetch from API
    await new Promise((r) => setTimeout(r, 800));
    setRefreshing(false);
  });

  // Simulate initial load for skeleton
  useState(() => { setTimeout(() => setLoaded(true), 400); });

  // Sort conversations: unread first, then by updatedAt
  const sortedConversations = useMemo(() => {
    return Object.values(conversations).sort((a, b) => {
      if (a.unreadCount > 0 && b.unreadCount === 0) return -1;
      if (b.unreadCount > 0 && a.unreadCount === 0) return 1;
      return (b.updatedAt ?? b.createdAt).localeCompare(a.updatedAt ?? a.createdAt);
    });
  }, [conversations]);

  const handleSelect = useCallback((id: string) => {
    haptic("light");
    onSelectConversation(id);
  }, [haptic, onSelectConversation]);

  return (
    <div className="flex flex-col h-full">
      {/* Header — iOS large title style */}
      <div className="flex items-center justify-between px-4 pt-[env(safe-area-inset-top)] shrink-0">
        <div className="pt-3 pb-2">
          <h1
            className="large-title text-white font-bold transition-all"
            style={{
              fontSize: `${34 - progress * 17}px`,
              opacity: collapsed ? 0.9 : 1,
            }}
          >
            Messages
          </h1>
          <StaleIndicator cacheKey="conversations" />
        </div>
      </div>

      {/* Refresh indicator */}
      {refreshing && (
        <div className="flex items-center justify-center py-2 shrink-0" role="status" aria-label="Refreshing">
          <Loader2 className="w-4 h-4 text-[var(--forge-accent)] animate-spin" />
        </div>
      )}

      {/* Conversation list */}
      {!loaded ? (
        <ConversationListSkeleton />
      ) : (
        <div ref={(el) => { (scrollRef as React.MutableRefObject<HTMLDivElement | null>).current = el; pullRef.current = el; }} className="flex-1 overflow-y-auto" onScroll={onScroll} role="list" aria-label="Conversations">
          {sortedConversations.map((conv) => (
            <ConversationRow
              key={conv.id}
              conversation={conv}
              lastMessagePreview={getLastMessagePreview(messages[conv.id])}
              lastMessageTime={getLastMessageTime(messages[conv.id])}
              agentStatus={conv.agentRole ? agents[conv.agentRole]?.status : undefined}
              pipelineRun={conv.pipelineId ? pipelineRuns.find((r) => r.id === conv.pipelineId) : undefined}
              onSelect={() => handleSelect(conv.id)}
              onMarkRead={() => markRead(conv.id)}
            />
          ))}

          {sortedConversations.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 px-8">
              <p className="text-sm text-[var(--forge-text-muted)] text-center">
                No conversations yet. Start a pipeline or message an agent.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Floating action button */}
      <button
        onClick={() => { haptic("medium"); openNewPipelineModal(); }}
        aria-label="New pipeline"
        className="absolute bottom-20 right-4 w-14 h-14 rounded-full bg-[var(--forge-accent)] text-white shadow-lg flex items-center justify-center active:scale-95 transition-transform"
        style={{ marginBottom: "env(safe-area-inset-bottom)" }}
      >
        <Plus className="w-6 h-6" />
      </button>
    </div>
  );
}

// ─── Conversation Row ───────────────────────────────

function ConversationRow({
  conversation,
  lastMessagePreview,
  lastMessageTime,
  agentStatus,
  pipelineRun,
  onSelect,
  onMarkRead,
}: {
  conversation: Conversation;
  lastMessagePreview: string;
  lastMessageTime: string;
  agentStatus?: AgentStatus;
  pipelineRun?: PipelineRun;
  onSelect: () => void;
  onMarkRead: () => void;
}) {
  const [swipeX, setSwipeX] = useState(0);
  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const isSwiping = useRef(false);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchStartY.current = e.touches[0].clientY;
    isSwiping.current = false;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchStartX.current;
    const dy = Math.abs(e.touches[0].clientY - touchStartY.current);

    // Only swipe horizontally
    if (dy > 30 && !isSwiping.current) return;
    if (Math.abs(dx) > 10) isSwiping.current = true;

    if (isSwiping.current) {
      // Clamp swipe: left reveals "mark read", right reveals "pin"
      setSwipeX(Math.max(-80, Math.min(80, dx)));
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (swipeX < -50) {
      // Swiped left → mark read
      onMarkRead();
    }
    // Reset
    setSwipeX(0);
    isSwiping.current = false;
  }, [swipeX, onMarkRead]);

  const isAgentDm = conversation.type === "agent_dm";
  const isPipeline = conversation.type === "pipeline";
  const agentInfo = conversation.agentRole ? AGENT_REGISTRY[conversation.agentRole] : undefined;

  return (
    <div className="relative overflow-hidden">
      {/* Swipe action backgrounds */}
      <div className="absolute inset-0 flex">
        {/* Right action (pin) - revealed on swipe right */}
        <div className="flex items-center justify-center w-20 bg-[var(--forge-accent)]">
          <Pin className="w-5 h-5 text-white" />
        </div>
        <div className="flex-1" />
        {/* Left action (mark read) - revealed on swipe left */}
        <div className="flex items-center justify-center w-20 bg-[var(--forge-success)]">
          <CheckCheck className="w-5 h-5 text-white" />
        </div>
      </div>

      {/* Main row content */}
      <button
        onClick={() => { if (!isSwiping.current) onSelect(); }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        role="listitem"
        aria-label={`${conversation.title}${conversation.unreadCount > 0 ? `, ${conversation.unreadCount} unread` : ""}`}
        className="relative w-full flex items-center gap-3 px-4 py-3 bg-[var(--forge-bg)] text-left active:bg-[var(--forge-hover)] transition-transform"
        style={{ transform: `translateX(${swipeX}px)` }}
      >
        {/* Avatar */}
        <div className="relative shrink-0">
          {isAgentDm && agentInfo ? (
            <>
              <span className="text-2xl leading-none">{agentInfo.emoji}</span>
              {agentStatus && (
                <span
                  className={cn(
                    "absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-[var(--forge-bg)]",
                    STATUS_DOT[agentStatus],
                    agentStatus === "working" && "animate-pulse"
                  )}
                />
              )}
            </>
          ) : isPipeline ? (
            <div className="w-8 h-8 rounded-lg bg-[var(--forge-hover)] flex items-center justify-center">
              <Hash className="w-4 h-4 text-[var(--forge-text-muted)]" />
            </div>
          ) : (
            <div className="w-8 h-8 rounded-full bg-[var(--forge-accent)] flex items-center justify-center text-white text-sm font-bold">
              {conversation.title[0]?.toUpperCase() ?? "#"}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span
              className={cn(
                "text-sm truncate",
                conversation.unreadCount > 0
                  ? "font-semibold text-white"
                  : "text-[var(--forge-text)]"
              )}
            >
              {conversation.title}
            </span>
            <span className="text-[10px] text-[var(--forge-text-muted)] shrink-0">
              {lastMessageTime}
            </span>
          </div>

          <div className="flex items-center justify-between gap-2 mt-0.5">
            <span
              className={cn(
                "text-xs truncate",
                conversation.unreadCount > 0
                  ? "text-[var(--forge-text)]"
                  : "text-[var(--forge-text-muted)]"
              )}
            >
              {isPipeline && pipelineRun ? (
                <span className={PIPELINE_STATUS_LABEL[pipelineRun.status].color}>
                  {PIPELINE_STATUS_LABEL[pipelineRun.status].text}
                  {lastMessagePreview ? ` — ${lastMessagePreview}` : ""}
                </span>
              ) : (
                lastMessagePreview || "No messages yet"
              )}
            </span>

            {conversation.unreadCount > 0 && (
              <span className="bg-[var(--forge-accent)] text-white text-[10px] font-bold px-1.5 py-px rounded-full min-w-[18px] text-center shrink-0">
                {conversation.unreadCount}
              </span>
            )}
          </div>
        </div>
      </button>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────

function getLastMessagePreview(msgs?: import("@/types/message").Message[]): string {
  if (!msgs || msgs.length === 0) return "";
  const last = msgs[msgs.length - 1];
  return contentPreview(last.content);
}

function getLastMessageTime(msgs?: import("@/types/message").Message[]): string {
  if (!msgs || msgs.length === 0) return "";
  const last = msgs[msgs.length - 1];
  return formatRelativeTime(last.createdAt);
}

function contentPreview(content: MessageContent[]): string {
  for (const block of content) {
    if (block.type === "text") return block.text;
    if (block.type === "markdown") return block.markdown.slice(0, 80);
    if (block.type === "code") return `[Code: ${block.filename ?? block.language}]`;
    if (block.type === "approval_request") return `Approval: ${block.summary.slice(0, 50)}`;
    if (block.type === "pipeline_event") return `Pipeline: ${block.event}`;
    if (block.type === "file_attachment") return `${block.filename}`;
    if (block.type === "diff") return `[Diff: ${block.filename}]`;
    if (block.type === "cost_update") return `Cost: $${block.totalCost.toFixed(2)}`;
  }
  return "";
}

function formatRelativeTime(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
