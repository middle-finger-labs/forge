import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import {
  Search,
  Settings,
  Plus,
  Activity,
  MessageSquare,
  Hash,
  Terminal,
} from "lucide-react";
import { useLayoutStore } from "@/stores/layoutStore";
import { useConversationStore } from "@/stores/conversationStore";
import { AGENT_REGISTRY, AGENT_ROLES } from "@/types/agent";
import { cn } from "@/lib/utils";

// ─── Result types ────────────────────────────────────

type ResultKind = "recent" | "conversation" | "agent" | "command";

interface SwitcherResult {
  id: string;
  kind: ResultKind;
  label: string;
  sublabel?: string;
  icon?: string;
  iconComponent?: typeof Settings;
  action: () => void;
}

// ─── Fuzzy match ─────────────────────────────────────

function fuzzyMatch(query: string, target: string): { match: boolean; score: number } {
  const q = query.toLowerCase();
  const t = target.toLowerCase();

  // Exact substring match is best
  if (t.includes(q)) {
    const index = t.indexOf(q);
    // Prefer starts-with
    return { match: true, score: index === 0 ? 100 : 80 };
  }

  // Fuzzy: every character in query appears in order in target
  let qi = 0;
  let score = 0;
  let prevMatchIdx = -1;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      score += 10;
      // Bonus for consecutive chars
      if (ti === prevMatchIdx + 1) score += 5;
      // Bonus for matching at word start
      if (ti === 0 || t[ti - 1] === " " || t[ti - 1] === "-" || t[ti - 1] === "_") {
        score += 8;
      }
      prevMatchIdx = ti;
      qi++;
    }
  }

  return { match: qi === q.length, score };
}

// ─── Component ───────────────────────────────────────

export function QuickSwitcher() {
  const {
    closeQuickSwitcher,
    openNewPipelineModal,
    openSettings,
    closeSettings,
    closeActivityFeed,
  } = useLayoutStore();
  const { conversations, setActiveConversation } = useConversationStore();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Build command results
  const commands = useMemo((): SwitcherResult[] => {
    const close = () => { closeQuickSwitcher(); closeSettings(); closeActivityFeed(); };
    return [
      {
        id: "cmd-new-pipeline",
        kind: "command",
        label: "New Pipeline",
        sublabel: "Create a new pipeline",
        iconComponent: Plus,
        action: () => { close(); openNewPipelineModal(); },
      },
      {
        id: "cmd-settings",
        kind: "command",
        label: "Settings",
        sublabel: "Open application settings",
        iconComponent: Settings,
        action: () => { close(); openSettings(); },
      },
      {
        id: "cmd-activity",
        kind: "command",
        label: "Activity Feed",
        sublabel: "View all unread messages",
        iconComponent: Activity,
        action: () => { close(); useLayoutStore.getState().openActivityFeed(); },
      },
    ];
  }, [closeQuickSwitcher, closeSettings, closeActivityFeed, openNewPipelineModal, openSettings]);

  // Build conversation results
  const conversationResults = useMemo((): SwitcherResult[] => {
    const close = () => { closeQuickSwitcher(); closeSettings(); closeActivityFeed(); };
    return Object.values(conversations).map((c) => {
      const emoji = c.agentRole ? AGENT_REGISTRY[c.agentRole]?.emoji : undefined;
      return {
        id: c.id,
        kind: (c.unreadCount > 0 ? "recent" : "conversation") as ResultKind,
        label: c.title,
        sublabel: c.type === "pipeline" ? "Pipeline" : c.type === "agent_dm" ? "Direct Message" : "Conversation",
        icon: emoji,
        iconComponent: c.type === "pipeline" ? Hash : MessageSquare,
        action: () => { close(); setActiveConversation(c.id); },
      };
    });
  }, [conversations, closeQuickSwitcher, closeSettings, closeActivityFeed, setActiveConversation]);

  // Build agent results (separate from conversation — searches by role name, emoji, keywords)
  const agentResults = useMemo((): SwitcherResult[] => {
    const close = () => { closeQuickSwitcher(); closeSettings(); closeActivityFeed(); };
    return AGENT_ROLES.map((role): SwitcherResult => {
      const info = AGENT_REGISTRY[role];
      return {
        id: `agent-${role}`,
        kind: "agent",
        label: info.displayName,
        sublabel: role,
        icon: info.emoji,
        action: () => { close(); setActiveConversation(`dm-${role}`); },
      };
    });
  }, [closeQuickSwitcher, closeSettings, closeActivityFeed, setActiveConversation]);

  // Filter and rank results
  const results = useMemo(() => {
    const q = query.trim();

    if (!q) {
      // No query: show recents (unread first), then all conversations
      const unread = conversationResults
        .filter((r) => {
          const conv = conversations[r.id];
          return conv && conv.unreadCount > 0;
        })
        .map((r) => ({ ...r, kind: "recent" as ResultKind }));

      const rest = conversationResults
        .filter((r) => {
          const conv = conversations[r.id];
          return !conv || conv.unreadCount === 0;
        });

      return [...unread, ...rest].slice(0, 10);
    }

    // Check for command prefix
    const isCommand = q.startsWith(">");
    const searchQ = isCommand ? q.slice(1).trim() : q;

    if (isCommand && !searchQ) {
      return commands;
    }

    // Score everything
    type Scored = SwitcherResult & { score: number };
    const scored: Scored[] = [];

    const sources = isCommand ? commands : [...conversationResults, ...agentResults, ...commands];

    for (const item of sources) {
      // Match against label and sublabel
      const labelMatch = fuzzyMatch(searchQ, item.label);
      const subMatch = item.sublabel ? fuzzyMatch(searchQ, item.sublabel) : { match: false, score: 0 };

      if (labelMatch.match || subMatch.match) {
        const score = Math.max(labelMatch.score, subMatch.score);
        // Boost score for kind priority
        const kindBoost = item.kind === "recent" ? 20 : item.kind === "conversation" ? 10 : item.kind === "agent" ? 5 : 0;
        scored.push({ ...item, score: score + kindBoost });
      }
    }

    // Dedupe: if an agent result and conversation result point to the same DM, keep the higher-scored one
    const seen = new Set<string>();
    const deduped: Scored[] = [];
    scored.sort((a, b) => b.score - a.score);
    for (const item of scored) {
      // Normalize: agent-{role} and dm-{role} are the same destination
      const key = item.id.startsWith("agent-")
        ? `dm-${item.id.replace("agent-", "")}`
        : item.id;
      if (!seen.has(key)) {
        seen.add(key);
        deduped.push(item);
      }
    }

    return deduped.slice(0, 12);
  }, [query, conversationResults, agentResults, commands, conversations]);

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Scroll selected item into view
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const selected = list.children[selectedIndex] as HTMLElement | undefined;
    selected?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const execute = useCallback(
    (index: number) => {
      const item = results[index];
      if (item) item.action();
    },
    [results]
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      execute(selectedIndex);
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeQuickSwitcher();
    } else if (e.key === "Tab") {
      e.preventDefault();
      // Tab to cycle through
      setSelectedIndex((i) => (i + 1) % Math.max(results.length, 1));
    }
  };

  // Group results by kind for display
  const grouped = useMemo(() => {
    const groups: Array<{ label: string; items: Array<SwitcherResult & { globalIndex: number }> }> = [];
    let currentKind: ResultKind | null = null;
    let currentGroup: typeof groups[number] | null = null;

    results.forEach((item, i) => {
      if (item.kind !== currentKind) {
        currentKind = item.kind;
        const kindLabel =
          item.kind === "recent" ? "Recent" :
          item.kind === "conversation" ? "Conversations" :
          item.kind === "agent" ? "Agents" :
          "Commands";
        currentGroup = { label: kindLabel, items: [] };
        groups.push(currentGroup);
      }
      currentGroup!.items.push({ ...item, globalIndex: i });
    });

    return groups;
  }, [results]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeQuickSwitcher();
      }}
    >
      <div className="w-[560px] bg-[var(--forge-sidebar)] rounded-xl shadow-2xl border border-[var(--forge-border)] overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--forge-border)]">
          <Search className="w-4 h-4 shrink-0" style={{ color: "var(--forge-text-muted)" }} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search conversations, agents, or type > for commands..."
            className="w-full bg-transparent text-white text-sm outline-none placeholder:text-[var(--forge-text-muted)]"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="text-xs shrink-0 cursor-pointer"
              style={{ color: "var(--forge-text-muted)" }}
            >
              Clear
            </button>
          )}
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[360px] overflow-y-auto py-1">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <Terminal className="w-6 h-6 mx-auto mb-2" style={{ color: "var(--forge-text-muted)", opacity: 0.5 }} />
              <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
                No results for "{query}"
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--forge-text-muted)", opacity: 0.6 }}>
                Type &gt; to search commands
              </p>
            </div>
          ) : (
            grouped.map((group) => (
              <div key={group.label}>
                <div
                  className="px-4 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  {group.label}
                </div>
                {group.items.map((item) => {
                  const Icon = item.iconComponent;
                  const isSelected = item.globalIndex === selectedIndex;

                  return (
                    <button
                      key={item.id}
                      onClick={() => execute(item.globalIndex)}
                      onMouseEnter={() => setSelectedIndex(item.globalIndex)}
                      className={cn(
                        "flex items-center gap-3 w-full px-4 py-2 text-left text-sm transition-colors cursor-pointer",
                        isSelected
                          ? "bg-[var(--forge-active)] text-white"
                          : "text-[var(--forge-text)] hover:bg-[var(--forge-hover)]"
                      )}
                    >
                      {/* Icon */}
                      {item.icon ? (
                        <span className="text-base w-6 text-center shrink-0">
                          {item.icon}
                        </span>
                      ) : Icon ? (
                        <span className="w-6 flex justify-center shrink-0">
                          <Icon className="w-4 h-4" style={{ color: isSelected ? "white" : "var(--forge-text-muted)" }} />
                        </span>
                      ) : (
                        <span className="w-6 shrink-0" />
                      )}

                      {/* Label */}
                      <div className="min-w-0 flex-1">
                        <span className="truncate block">{item.label}</span>
                      </div>

                      {/* Sublabel */}
                      {item.sublabel && (
                        <span
                          className="text-xs shrink-0"
                          style={{ color: isSelected ? "rgba(255,255,255,0.7)" : "var(--forge-text-muted)" }}
                        >
                          {item.sublabel}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-[var(--forge-border)] flex gap-4 text-[10px] text-[var(--forge-text-muted)]">
          <span>
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">↑↓</kbd> navigate
          </span>
          <span>
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">↵</kbd> open
          </span>
          <span>
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">⇥</kbd> cycle
          </span>
          <span>
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">&gt;</kbd> commands
          </span>
          <span className="ml-auto">
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}
