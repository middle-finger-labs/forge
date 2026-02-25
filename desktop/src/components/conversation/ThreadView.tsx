import { useMemo, useCallback } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { MessageBubble } from "./MessageBubble";
import { MessageInput } from "./MessageInput";
import type { Message, MessageContent } from "@/types/message";
import { X, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Props ──────────────────────────────────────────────

interface ThreadViewProps {
  /** The ID of the parent message that started the thread */
  parentMessageId: string;
  /** Conversation ID the thread belongs to */
  conversationId: string;
  /** Close the thread panel */
  onClose: () => void;
}

// ─── ThreadView ─────────────────────────────────────────

export function ThreadView({
  parentMessageId,
  conversationId,
  onClose,
}: ThreadViewProps) {
  const { messages: allMessages, addMessage } = useConversationStore();

  const conversationMessages = allMessages[conversationId] ?? [];

  // Find parent message
  const parentMessage = useMemo(
    () => conversationMessages.find((m) => m.id === parentMessageId),
    [conversationMessages, parentMessageId]
  );

  // Find thread replies
  const threadReplies = useMemo(
    () =>
      conversationMessages.filter((m) => m.threadId === parentMessageId),
    [conversationMessages, parentMessageId]
  );

  // Send reply in thread
  const handleSend = useCallback(
    (content: MessageContent[]) => {
      addMessage({
        id: `local-thread-${Date.now()}`,
        conversationId,
        author: { type: "user", userId: "me", name: "You" },
        content,
        threadId: parentMessageId,
        createdAt: new Date().toISOString(),
      });
    },
    [conversationId, parentMessageId, addMessage]
  );

  if (!parentMessage) {
    return (
      <div className="flex flex-col h-full bg-[var(--forge-channel)] border-l border-[var(--forge-border)]">
        <ThreadHeader replyCount={0} onClose={onClose} />
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--forge-text-muted)]">
          Message not found
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[var(--forge-channel)] border-l border-[var(--forge-border)]">
      {/* Header */}
      <ThreadHeader replyCount={threadReplies.length} onClose={onClose} />

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Parent message */}
        <div className="px-4 pt-3 pb-3 border-b border-[var(--forge-border)]">
          <MessageBubble message={parentMessage} />
        </div>

        {/* Thread replies */}
        {threadReplies.length > 0 ? (
          <div className="px-4 py-2">
            <div className="flex items-center gap-2 py-2 mb-1">
              <span className="text-xs font-medium text-[var(--forge-text-muted)]">
                {threadReplies.length}{" "}
                {threadReplies.length === 1 ? "reply" : "replies"}
              </span>
              <div className="flex-1 h-px bg-[var(--forge-border)]" />
            </div>

            <div className="space-y-1">
              {threadReplies.map((msg, i) => {
                const prev = i > 0 ? threadReplies[i - 1] : null;
                const grouped = isGrouped(msg, prev);
                return (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    grouped={grouped}
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center px-4">
            <MessageSquare className="w-8 h-8 text-[var(--forge-text-muted)] opacity-40 mb-3" />
            <p className="text-sm text-[var(--forge-text-muted)]">
              No replies yet. Start the discussion.
            </p>
          </div>
        )}
      </div>

      {/* Thread input */}
      <MessageInput
        conversationTitle="this thread"
        onSend={handleSend}
      />
    </div>
  );
}

// ─── Thread header ──────────────────────────────────────

function ThreadHeader({
  replyCount,
  onClose,
}: {
  replyCount: number;
  onClose: () => void;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--forge-border)] shrink-0">
      <div className="flex items-center gap-2">
        <MessageSquare className="w-4 h-4 text-[var(--forge-text-muted)]" />
        <h3 className="text-sm font-semibold text-white">Thread</h3>
        {replyCount > 0 && (
          <span className="text-xs text-[var(--forge-text-muted)]">
            {replyCount} {replyCount === 1 ? "reply" : "replies"}
          </span>
        )}
      </div>
      <button
        onClick={onClose}
        className={cn(
          "p-1 rounded",
          "hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
        )}
        title="Close thread"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────

function isGrouped(msg: Message, prev: Message | null): boolean {
  if (!prev) return false;
  if (msg.author.type === "system") return false;

  const sameAuthor =
    msg.author.type === prev.author.type &&
    (msg.author.type === "agent" && prev.author.type === "agent"
      ? msg.author.role === prev.author.role
      : msg.author.type === "user" && prev.author.type === "user"
        ? msg.author.userId === prev.author.userId
        : false);

  if (!sameAuthor) return false;

  const timeDiff =
    new Date(msg.createdAt).getTime() - new Date(prev.createdAt).getTime();
  return timeDiff < 5 * 60 * 1000;
}
