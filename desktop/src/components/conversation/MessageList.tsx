import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { MessageBubble } from "./MessageBubble";
import type { Message } from "@/types/message";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

// ─── Props ──────────────────────────────────────────────

interface MessageListProps {
  messages: Message[];
  /** Called when user scrolls to top — load older messages */
  onLoadMore?: () => void;
  /** Whether older messages are being loaded */
  loadingMore?: boolean;
  /** Whether there are more messages to load */
  hasMore?: boolean;
  /** Callback to open thread panel */
  onOpenThread?: (messageId: string) => void;
  /** Optional thinking indicator rendered below the last message */
  thinkingIndicator?: React.ReactNode;
}

// ─── Date separator ─────────────────────────────────────

function formatDateSeparator(date: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const msgDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (msgDate.getTime() === today.getTime()) return "Today";
  if (msgDate.getTime() === yesterday.getTime()) return "Yesterday";

  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year:
      date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

// ─── Grouping helpers ───────────────────────────────────

interface MessageGroup {
  type: "message";
  message: Message;
  grouped: boolean;
}

interface DateSeparator {
  type: "date";
  date: string;
  label: string;
}

type ListItem = MessageGroup | DateSeparator;

function buildListItems(messages: Message[]): ListItem[] {
  const items: ListItem[] = [];
  let prevAuthorKey = "";
  let prevDate = "";
  let prevTimestamp = 0;

  for (const msg of messages) {
    const msgDate = new Date(msg.createdAt);
    const dateKey = msgDate.toDateString();

    // Insert date separator if day changed
    if (dateKey !== prevDate) {
      items.push({
        type: "date",
        date: dateKey,
        label: formatDateSeparator(msgDate),
      });
      prevAuthorKey = "";
      prevDate = dateKey;
    }

    // Determine author key for grouping
    const authorKey =
      msg.author.type === "agent"
        ? `agent:${msg.author.role}`
        : msg.author.type === "user"
          ? `user:${msg.author.userId}`
          : "system";

    // Group if same author and within 5 minutes
    const timeDiff = msgDate.getTime() - prevTimestamp;
    const grouped =
      authorKey === prevAuthorKey &&
      timeDiff < 5 * 60 * 1000 &&
      msg.author.type !== "system";

    items.push({
      type: "message",
      message: msg,
      grouped,
    });

    prevAuthorKey = authorKey;
    prevTimestamp = msgDate.getTime();
  }

  return items;
}

// ─── MessageList ────────────────────────────────────────

export function MessageList({
  messages,
  onLoadMore,
  loadingMore = false,
  hasMore = false,
  onOpenThread,
  thinkingIndicator,
}: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [showNewPill, setShowNewPill] = useState(false);
  const isAtBottomRef = useRef(true);
  const prevMessageCountRef = useRef(messages.length);

  const items = useMemo(() => buildListItems(messages), [messages]);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const item = items[index];
      if (item.type === "date") return 40;
      // Estimate based on content block count
      const blockCount = item.message.content.length;
      return item.grouped ? 28 + blockCount * 30 : 52 + blockCount * 30;
    },
    overscan: 10,
  });

  // Scroll to bottom when new messages arrive (if already at bottom)
  useEffect(() => {
    if (messages.length > prevMessageCountRef.current) {
      if (isAtBottomRef.current) {
        // Scroll to the new bottom
        requestAnimationFrame(() => {
          virtualizer.scrollToIndex(items.length - 1, { align: "end" });
        });
      } else {
        setShowNewPill(true);
      }
    }
    prevMessageCountRef.current = messages.length;
  }, [messages.length, items.length, virtualizer]);

  // Track scroll position
  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;

    const distanceFromBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight;
    isAtBottomRef.current = distanceFromBottom < 80;

    // Hide "new messages" pill when scrolled to bottom
    if (isAtBottomRef.current && showNewPill) {
      setShowNewPill(false);
    }

    // Load more when scrolled to top
    if (el.scrollTop < 100 && hasMore && !loadingMore && onLoadMore) {
      onLoadMore();
    }
  }, [hasMore, loadingMore, onLoadMore, showNewPill]);

  // Initial scroll to bottom
  useEffect(() => {
    if (items.length > 0) {
      requestAnimationFrame(() => {
        virtualizer.scrollToIndex(items.length - 1, { align: "end" });
      });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const scrollToBottom = useCallback(() => {
    virtualizer.scrollToIndex(items.length - 1, {
      align: "end",
      behavior: "smooth",
    });
    setShowNewPill(false);
  }, [virtualizer, items.length]);

  return (
    <div className="relative flex-1 min-h-0">
      <div
        ref={parentRef}
        onScroll={handleScroll}
        className="h-full overflow-y-auto px-5"
      >
        {/* Loading indicator at top */}
        {loadingMore && (
          <div className="flex items-center justify-center py-3">
            <div className="w-4 h-4 border-2 border-[var(--forge-accent)] border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const item = items[virtualItem.index];

            return (
              <div
                key={virtualItem.key}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                {item.type === "date" ? (
                  <DateSeparatorRow label={item.label} />
                ) : (
                  <MessageBubble
                    message={item.message}
                    grouped={item.grouped}
                    onOpenThread={onOpenThread}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Thinking indicator — rendered below the virtualized list */}
        {thinkingIndicator && (
          <div className="pb-4">{thinkingIndicator}</div>
        )}
      </div>

      {/* "New messages" pill */}
      {showNewPill && (
        <button
          onClick={scrollToBottom}
          className={cn(
            "absolute bottom-4 left-1/2 -translate-x-1/2",
            "flex items-center gap-1.5 px-4 py-1.5 rounded-full",
            "bg-[var(--forge-accent)] text-white text-xs font-medium",
            "shadow-lg hover:bg-[var(--forge-active)] transition-colors",
            "animate-in fade-in slide-in-from-bottom-2"
          )}
        >
          <ChevronDown className="w-3 h-3" />
          New messages
        </button>
      )}
    </div>
  );
}

// ─── Date separator row ─────────────────────────────────

function DateSeparatorRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-3">
      <div className="flex-1 h-px bg-[var(--forge-border)]" />
      <span className="text-[11px] font-medium text-[var(--forge-text-muted)] shrink-0 px-2 py-0.5 rounded-full border border-[var(--forge-border)] bg-[var(--forge-channel)]">
        {label}
      </span>
      <div className="flex-1 h-px bg-[var(--forge-border)]" />
    </div>
  );
}
