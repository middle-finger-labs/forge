import { useState, useMemo, useCallback } from "react";
import {
  CheckCheck,
  MessageSquare,
  Hash,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { useConversationStore } from "@/stores/conversationStore";
import { AGENT_REGISTRY } from "@/types/agent";
import type { Message, MessageContent, MessageAuthor } from "@/types/message";
import type { Conversation } from "@/types/conversation";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────

type ActivityFilter = "all" | "pipelines" | "dms" | "approvals";

interface UnreadGroup {
  conversation: Conversation;
  messages: Message[];
}

// ─── Component ───────────────────────────────────────

interface ActivityFeedProps {
  onClose?: () => void;
}

export function ActivityFeed({ onClose }: ActivityFeedProps) {
  const { conversations, messages, setActiveConversation, markRead } =
    useConversationStore();
  const [filter, setFilter] = useState<ActivityFilter>("all");

  // Group unread messages by conversation
  const unreadGroups = useMemo(() => {
    const groups: UnreadGroup[] = [];

    for (const conv of Object.values(conversations)) {
      if (conv.unreadCount === 0) continue;

      // Apply filter
      if (filter === "pipelines" && conv.type !== "pipeline") continue;
      if (filter === "dms" && conv.type !== "agent_dm") continue;

      const convMessages = messages[conv.id] ?? [];

      if (filter === "approvals") {
        const approvalMsgs = convMessages.filter((m) =>
          m.content.some((c) => c.type === "approval_request")
        );
        if (approvalMsgs.length === 0) continue;
        groups.push({ conversation: conv, messages: approvalMsgs });
      } else {
        // Take the last N unread messages
        const unreadSlice = convMessages.slice(-conv.unreadCount);
        if (unreadSlice.length > 0) {
          groups.push({ conversation: conv, messages: unreadSlice });
        }
      }
    }

    // Sort by most recent message
    groups.sort((a, b) => {
      const aTime = a.messages[a.messages.length - 1]?.createdAt ?? "";
      const bTime = b.messages[b.messages.length - 1]?.createdAt ?? "";
      return bTime.localeCompare(aTime);
    });

    return groups;
  }, [conversations, messages, filter]);

  const totalUnread = useMemo(
    () =>
      Object.values(conversations).reduce(
        (sum, c) => sum + c.unreadCount,
        0
      ),
    [conversations]
  );

  const handleMarkAllRead = useCallback(() => {
    for (const conv of Object.values(conversations)) {
      if (conv.unreadCount > 0) {
        markRead(conv.id);
      }
    }
  }, [conversations, markRead]);

  const handleJump = useCallback(
    (conversationId: string) => {
      setActiveConversation(conversationId);
      onClose?.();
    },
    [setActiveConversation, onClose]
  );

  return (
    <div className="flex flex-col h-full" style={{ background: "var(--forge-channel)" }}>
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: "1px solid var(--forge-border)" }}
      >
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold" style={{ color: "var(--forge-text)" }}>
            Activity
          </h2>
          {totalUnread > 0 && (
            <span
              className="text-[10px] font-bold px-1.5 py-px rounded-full min-w-[18px] text-center text-white"
              style={{ background: "var(--forge-accent)" }}
            >
              {totalUnread}
            </span>
          )}
        </div>

        {totalUnread > 0 && (
          <button
            onClick={handleMarkAllRead}
            className="flex items-center gap-1 text-xs transition-colors cursor-pointer"
            style={{ color: "var(--forge-accent)" }}
          >
            <CheckCheck className="w-3.5 h-3.5" />
            Mark all read
          </button>
        )}
      </div>

      {/* Filters */}
      <div
        className="flex items-center gap-1 px-4 py-2 shrink-0"
        style={{ borderBottom: "1px solid var(--forge-border)" }}
      >
        {FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={cn(
              "px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer",
              filter === f.id
                ? "text-white"
                : "text-[var(--forge-text-muted)] hover:text-[var(--forge-text)]"
            )}
            style={{
              background:
                filter === f.id ? "var(--forge-accent)" : "transparent",
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Feed */}
      <div className="flex-1 overflow-y-auto">
        {unreadGroups.length === 0 ? (
          <EmptyState filter={filter} />
        ) : (
          <div className="py-2">
            {unreadGroups.map((group) => (
              <ConversationGroup
                key={group.conversation.id}
                group={group}
                onJump={handleJump}
                onMarkRead={() => markRead(group.conversation.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Filter definitions ──────────────────────────────

const FILTERS: Array<{ id: ActivityFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "pipelines", label: "Pipelines" },
  { id: "dms", label: "Agent DMs" },
  { id: "approvals", label: "Approvals" },
];

// ─── Conversation group ──────────────────────────────

function ConversationGroup({
  group,
  onJump,
  onMarkRead,
}: {
  group: UnreadGroup;
  onJump: (id: string) => void;
  onMarkRead: () => void;
}) {
  const { conversation, messages } = group;
  const isPipeline = conversation.type === "pipeline";

  return (
    <div
      className="mx-2 mb-2 rounded-lg overflow-hidden"
      style={{ border: "1px solid var(--forge-border)" }}
    >
      {/* Group header */}
      <button
        onClick={() => onJump(conversation.id)}
        className="flex items-center justify-between w-full px-3 py-2 text-left transition-colors cursor-pointer"
        style={{ background: "var(--forge-bg)" }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.background = "var(--forge-hover)")
        }
        onMouseLeave={(e) =>
          (e.currentTarget.style.background = "var(--forge-bg)")
        }
      >
        <div className="flex items-center gap-2 min-w-0">
          {isPipeline ? (
            <Hash className="w-3.5 h-3.5 shrink-0" style={{ color: "var(--forge-text-muted)" }} />
          ) : (
            <MessageSquare className="w-3.5 h-3.5 shrink-0" style={{ color: "var(--forge-text-muted)" }} />
          )}
          <span className="text-sm font-medium truncate" style={{ color: "var(--forge-text)" }}>
            {conversation.title}
          </span>
          <span
            className="text-[10px] font-bold px-1.5 py-px rounded-full text-white shrink-0"
            style={{ background: "var(--forge-accent)" }}
          >
            {conversation.unreadCount} new
          </span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onMarkRead();
          }}
          className="text-[10px] shrink-0 transition-colors cursor-pointer"
          style={{ color: "var(--forge-text-muted)" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-accent)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
        >
          Mark read
        </button>
      </button>

      {/* Message previews */}
      <div>
        {messages.slice(-5).map((msg) => (
          <button
            key={msg.id}
            onClick={() => onJump(conversation.id)}
            className="flex items-start gap-2.5 w-full px-3 py-2 text-left transition-colors cursor-pointer"
            style={{ borderTop: "1px solid var(--forge-border)" }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = "var(--forge-hover)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background = "transparent")
            }
          >
            <AuthorAvatar author={msg.author} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-medium" style={{ color: "var(--forge-text)" }}>
                  {authorName(msg.author)}
                </span>
                <span className="text-[10px]" style={{ color: "var(--forge-text-muted)" }}>
                  {formatTime(msg.createdAt)}
                </span>
              </div>
              <p className="text-xs truncate mt-0.5" style={{ color: "var(--forge-text-muted)" }}>
                {contentPreview(msg.content)}
              </p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Author avatar ───────────────────────────────────

function AuthorAvatar({ author }: { author: MessageAuthor }) {
  if (author.type === "agent") {
    const info = AGENT_REGISTRY[author.role];
    return <span className="text-sm shrink-0 mt-0.5">{info?.emoji ?? "🤖"}</span>;
  }
  if (author.type === "user") {
    return (
      <span
        className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0 mt-0.5"
        style={{ background: "var(--forge-accent)" }}
      >
        {author.name[0]?.toUpperCase() ?? "U"}
      </span>
    );
  }
  // system
  return (
    <span className="text-sm shrink-0 mt-0.5" style={{ color: "var(--forge-text-muted)" }}>
      ⚙
    </span>
  );
}

// ─── Helpers ─────────────────────────────────────────

function authorName(author: MessageAuthor): string {
  if (author.type === "agent") return author.name;
  if (author.type === "user") return author.name;
  return "System";
}

function contentPreview(content: MessageContent[]): string {
  for (const block of content) {
    if (block.type === "text") return block.text;
    if (block.type === "markdown") return block.markdown.slice(0, 100);
    if (block.type === "code") return `[Code: ${block.filename ?? block.language}]`;
    if (block.type === "approval_request") return `⏳ Approval requested: ${block.summary.slice(0, 60)}`;
    if (block.type === "pipeline_event") return `Pipeline: ${block.event}`;
    if (block.type === "file_attachment") return `📎 ${block.filename}`;
    if (block.type === "diff") return `[Diff: ${block.filename}]`;
    if (block.type === "cost_update") return `💰 Cost update: $${block.totalCost.toFixed(2)}`;
  }
  return "";
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h`;

  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ─── Empty state ─────────────────────────────────────

function EmptyState({ filter }: { filter: ActivityFilter }) {
  const messages: Record<ActivityFilter, { icon: typeof Clock; text: string }> = {
    all: { icon: CheckCheck, text: "You're all caught up" },
    pipelines: { icon: Hash, text: "No unread pipeline messages" },
    dms: { icon: MessageSquare, text: "No unread DMs" },
    approvals: { icon: AlertTriangle, text: "No pending approvals" },
  };

  const { icon: Icon, text } = messages[filter];

  return (
    <div className="flex flex-col items-center justify-center h-full py-16">
      <Icon className="w-10 h-10 mb-3" style={{ color: "var(--forge-text-muted)", opacity: 0.5 }} />
      <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
        {text}
      </p>
    </div>
  );
}
