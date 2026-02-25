import { useState, useMemo } from "react";
import { Activity, Hash, Plus, Settings, Zap } from "lucide-react";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { MOCK_ACTIVITY, type ActivityEvent } from "@/data/mockData";
import { AGENT_ROLES, AGENT_REGISTRY } from "@/types/agent";
import type { PipelineRun, PipelineStatus } from "@/types/pipeline";
import type { AgentStatus } from "@/types/agent";
import { cn } from "@/lib/utils";

const STATUS_DOT: Record<AgentStatus, string> = {
  idle: "bg-[var(--forge-success)]",
  working: "bg-[var(--forge-warning)]",
  waiting: "bg-[var(--forge-warning)]",
  error: "bg-[var(--forge-error)]",
  offline: "bg-gray-500",
};

const PIPELINE_STATUS_ICON: Record<PipelineStatus, string> = {
  running: "\u{1F7E2}",
  completed: "\u2705",
  failed: "\u274C",
  paused: "\u23F8\uFE0F",
  awaiting_approval: "\u23F8\uFE0F",
  pending: "\u23F3",
};

interface SidebarProps {
  pipelineRuns: PipelineRun[];
}

type SidebarSection = "agents" | "pipelines" | "activity";

export function Sidebar({ pipelineRuns }: SidebarProps) {
  const { activeConversationId, setActiveConversation, conversations, agents } =
    useConversationStore();
  const { openNewPipelineModal, openSettings, openActivityFeed, activityFeedOpen, closeActivityFeed, closeSettings } = useLayoutStore();
  const [expandedSections, setExpandedSections] = useState<Set<SidebarSection>>(
    new Set(["agents", "pipelines", "activity"])
  );

  const toggleSection = (section: SidebarSection) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  };

  const handleSelectConversation = (id: string) => {
    setActiveConversation(id);
    closeActivityFeed();
    closeSettings();
  };

  const totalUnread = useMemo(
    () => Object.values(conversations).reduce((sum, c) => sum + c.unreadCount, 0),
    [conversations]
  );

  const pipelineConversations = Object.values(conversations).filter(
    (c) => c.type === "pipeline"
  );

  return (
    <div className="flex flex-col h-full bg-[var(--forge-sidebar)]">
      {/* Server header */}
      <div className="flex items-center justify-between h-12 px-4 border-b border-[var(--forge-border)] shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Zap className="w-4 h-4 text-[var(--forge-accent)] shrink-0" />
          <div className="min-w-0">
            <div className="text-sm font-bold text-white truncate leading-tight">
              Forge
            </div>
            <div className="text-[10px] text-[var(--forge-text-muted)] truncate leading-tight">
              Middle Finger Labs
            </div>
          </div>
        </div>
        <button
          onClick={openSettings}
          className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors shrink-0 cursor-pointer"
          title="Settings"
        >
          <Settings className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* All Activity button */}
      <button
        onClick={openActivityFeed}
        className={cn(
          "flex items-center gap-2.5 w-full px-4 py-[7px] text-sm text-left",
          "hover:bg-[var(--forge-hover)] transition-colors",
          activityFeedOpen && "bg-[var(--forge-active)] text-white"
        )}
      >
        <Activity className="w-4 h-4 shrink-0 text-[var(--forge-text-muted)]" />
        <span className="text-[var(--forge-text)] flex-1">All Activity</span>
        {totalUnread > 0 && (
          <span className="bg-[var(--forge-accent)] text-white text-[10px] font-bold px-1.5 py-px rounded-full min-w-[18px] text-center shrink-0">
            {totalUnread}
          </span>
        )}
      </button>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {/* Direct Messages (Agents) */}
        <SectionHeader
          label="Direct Messages"
          expanded={expandedSections.has("agents")}
          onToggle={() => toggleSection("agents")}
        />
        {expandedSections.has("agents") && (
          <div className="pb-2">
            {AGENT_ROLES.map((role, i) => {
              const info = AGENT_REGISTRY[role];
              const agent = agents[role];
              const status = agent?.status ?? "offline";
              const convId = `dm-${role}`;

              return (
                <button
                  key={role}
                  onClick={() => handleSelectConversation(convId)}
                  className={cn(
                    "flex items-center gap-2.5 w-full px-4 py-[5px] text-sm text-left",
                    "hover:bg-[var(--forge-hover)] transition-colors",
                    activeConversationId === convId &&
                      "bg-[var(--forge-active)] text-white"
                  )}
                >
                  <span className="relative shrink-0">
                    <span className="text-base leading-none">{info.emoji}</span>
                    <span
                      className={cn(
                        "absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-[var(--forge-sidebar)]",
                        STATUS_DOT[status],
                        status === "working" && "animate-pulse"
                      )}
                    />
                  </span>
                  <span className="truncate text-[var(--forge-text)] flex-1">
                    {info.displayName}
                  </span>
                  {status === "working" ? (
                    <span className="ml-auto inline-flex items-center gap-0.5 shrink-0">
                      {[0, 1, 2].map((j) => (
                        <span
                          key={j}
                          className="w-1 h-1 rounded-full bg-[var(--forge-warning)]"
                          style={{
                            animation: "typing-bounce 1.4s infinite",
                            animationDelay: `${j * 0.2}s`,
                          }}
                        />
                      ))}
                    </span>
                  ) : (
                    <span className="ml-auto text-[10px] text-[var(--forge-text-muted)] font-mono opacity-0 group-hover:opacity-100 shrink-0">
                      {"\u2318"}{i + 1}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* Pipelines */}
        <SectionHeader
          label="Pipelines"
          expanded={expandedSections.has("pipelines")}
          onToggle={() => toggleSection("pipelines")}
          action={
            <button
              onClick={openNewPipelineModal}
              className="p-0.5 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
              title="New Pipeline (Cmd+N)"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          }
        />
        {expandedSections.has("pipelines") && (
          <div className="pb-2">
            {pipelineConversations.map((conv) => {
              const run = pipelineRuns.find(
                (r) => r.id === conv.pipelineId
              );
              return (
                <button
                  key={conv.id}
                  onClick={() => handleSelectConversation(conv.id)}
                  className={cn(
                    "flex items-center gap-2 w-full px-4 py-[5px] text-sm text-left",
                    "hover:bg-[var(--forge-hover)] transition-colors",
                    activeConversationId === conv.id &&
                      "bg-[var(--forge-active)] text-white"
                  )}
                >
                  <Hash className="w-3.5 h-3.5 shrink-0 text-[var(--forge-text-muted)]" />
                  <span className="truncate text-[var(--forge-text)]">
                    {conv.title}
                  </span>
                  <span className="ml-auto flex items-center gap-1.5 shrink-0">
                    {conv.unreadCount > 0 && (
                      <span className="bg-[var(--forge-accent)] text-white text-[10px] font-bold px-1.5 py-px rounded-full min-w-[18px] text-center">
                        {conv.unreadCount}
                      </span>
                    )}
                    {run && (
                      <span className="text-xs" title={run.status}>
                        {PIPELINE_STATUS_ICON[run.status]}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* Activity */}
        <SectionHeader
          label="Activity"
          expanded={expandedSections.has("activity")}
          onToggle={() => toggleSection("activity")}
        />
        {expandedSections.has("activity") && (
          <div className="pb-2 px-4 space-y-1.5">
            {MOCK_ACTIVITY.map((evt) => (
              <ActivityItem key={evt.id} event={evt} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SectionHeader({
  label,
  expanded,
  onToggle,
  action,
}: {
  label: string;
  expanded: boolean;
  onToggle: () => void;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center px-4 pt-3 pb-1">
      <button
        onClick={onToggle}
        className="flex items-center gap-1 text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider hover:text-white transition-colors"
      >
        <span
          className={cn(
            "text-[10px] transition-transform",
            expanded ? "rotate-90" : ""
          )}
        >
          ▶
        </span>
        {label}
      </button>
      {action && <div className="ml-auto">{action}</div>}
    </div>
  );
}

function ActivityItem({ event }: { event: ActivityEvent }) {
  const typeIcon: Record<ActivityEvent["type"], string> = {
    message: "\u{1F4AC}",
    status_change: "\u{1F504}",
    approval_request: "\u{1F514}",
    error: "\u26A0\uFE0F",
  };

  const age = formatRelativeTime(event.timestamp);

  return (
    <div className="flex gap-2 text-xs">
      <span className="shrink-0 mt-px">{typeIcon[event.type]}</span>
      <div className="min-w-0">
        <p className="text-[var(--forge-text)] truncate">{event.summary}</p>
        <p className="text-[var(--forge-text-muted)]">{age}</p>
      </div>
    </div>
  );
}

function formatRelativeTime(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
