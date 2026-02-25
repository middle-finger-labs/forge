import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole, AgentStatus } from "@/types/agent";
import { AGENT_BEHAVIORS } from "@/hooks/useAgentChat";
import type { QuickAction } from "@/hooks/useAgentChat";
import {
  MessageSquare,
  Cpu,
  Clock,
  Sparkles,
  ChevronRight,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status config ───────────────────────────────────

const STATUS_CONFIG: Record<
  AgentStatus,
  { color: string; dotColor: string; label: string; pulse?: boolean }
> = {
  idle: {
    color: "text-[var(--forge-success)]",
    dotColor: "bg-[var(--forge-success)]",
    label: "Online",
  },
  working: {
    color: "text-[var(--forge-warning)]",
    dotColor: "bg-[var(--forge-warning)]",
    label: "Working",
    pulse: true,
  },
  waiting: {
    color: "text-[var(--forge-warning)]",
    dotColor: "bg-[var(--forge-warning)]",
    label: "Waiting for input",
  },
  error: {
    color: "text-[var(--forge-error)]",
    dotColor: "bg-[var(--forge-error)]",
    label: "Error",
  },
  offline: {
    color: "text-gray-400",
    dotColor: "bg-gray-500",
    label: "Offline",
  },
};

// ─── Agent role accent colors ────────────────────────

const ROLE_ACCENT: Record<AgentRole, string> = {
  ba: "from-blue-500/20 to-blue-500/5",
  researcher: "from-purple-500/20 to-purple-500/5",
  architect: "from-amber-500/20 to-amber-500/5",
  pm: "from-green-500/20 to-green-500/5",
  engineer: "from-cyan-500/20 to-cyan-500/5",
  qa: "from-pink-500/20 to-pink-500/5",
  cto: "from-red-500/20 to-red-500/5",
};

const ROLE_BORDER: Record<AgentRole, string> = {
  ba: "border-blue-500/30",
  researcher: "border-purple-500/30",
  architect: "border-amber-500/30",
  pm: "border-green-500/30",
  engineer: "border-cyan-500/30",
  qa: "border-pink-500/30",
  cto: "border-red-500/30",
};

// ─── Props ───────────────────────────────────────────

interface AgentProfileProps {
  agentRole: AgentRole;
  onClose?: () => void;
  onQuickAction?: (action: QuickAction) => void;
}

// ─── AgentProfile ────────────────────────────────────

export function AgentProfile({
  agentRole,
  onClose,
  onQuickAction,
}: AgentProfileProps) {
  const { agents, messages, conversations } = useConversationStore();
  const { closeDetailPanel } = useLayoutStore();

  const info = AGENT_REGISTRY[agentRole];
  const agent = agents[agentRole];
  const behavior = AGENT_BEHAVIORS[agentRole];
  const status = agent?.status ?? "offline";
  const statusConfig = STATUS_CONFIG[status];

  // Compute stats from conversation messages
  const convId = `dm-${agentRole}`;
  const conv = conversations[convId];
  const convMessages = messages[convId] ?? [];
  const agentMessages = convMessages.filter(
    (m) => m.author.type === "agent"
  );
  const userMessages = convMessages.filter(
    (m) => m.author.type === "user"
  );

  return (
    <div className="flex flex-col h-full bg-[var(--forge-sidebar)]">
      {/* Header */}
      <div className="flex items-center justify-between h-10 px-3 border-b border-[var(--forge-border)] shrink-0">
        <span className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          Agent Profile
        </span>
        <button
          onClick={onClose ?? closeDetailPanel}
          className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {/* Hero section with gradient background */}
        <div
          className={cn(
            "bg-gradient-to-b px-4 pt-6 pb-4",
            ROLE_ACCENT[agentRole]
          )}
        >
          {/* Avatar */}
          <div className="flex justify-center mb-3">
            <div className="relative">
              <div
                className={cn(
                  "w-20 h-20 rounded-2xl flex items-center justify-center text-4xl border-2",
                  ROLE_BORDER[agentRole],
                  "bg-[var(--forge-bg)]/60 backdrop-blur-sm"
                )}
              >
                {info.emoji}
              </div>
              {/* Status dot */}
              <div
                className={cn(
                  "absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-[3px] border-[var(--forge-sidebar)] flex items-center justify-center",
                  statusConfig.dotColor,
                  statusConfig.pulse && "animate-pulse"
                )}
              />
            </div>
          </div>

          {/* Name and status */}
          <div className="text-center">
            <h2 className="text-lg font-bold text-white">{info.displayName}</h2>
            <div className="flex items-center justify-center gap-1.5 mt-1">
              <span
                className={cn("text-xs font-medium", statusConfig.color)}
              >
                {statusConfig.label}
              </span>
            </div>
          </div>
        </div>

        {/* Current task */}
        {agent?.currentTask && status === "working" && (
          <div className="mx-3 mt-3 px-3 py-2.5 rounded-lg bg-[var(--forge-warning)]/5 border border-[var(--forge-warning)]/20">
            <div className="flex items-center gap-2 mb-1">
              <ThinkingDots />
              <span className="text-[10px] font-medium text-[var(--forge-warning)] uppercase tracking-wider">
                Currently Working
              </span>
            </div>
            <p className="text-xs text-[var(--forge-text)]">
              {agent.currentTask}
            </p>
          </div>
        )}

        {/* Description */}
        <div className="px-4 mt-4">
          <p className="text-xs text-[var(--forge-text-muted)] leading-relaxed">
            {behavior.description}
          </p>
        </div>

        {/* Specialties */}
        <div className="px-4 mt-4">
          <h3 className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
            Specialties
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {behavior.specialties.map((s) => (
              <span
                key={s}
                className="px-2 py-0.5 text-[11px] rounded-full bg-[var(--forge-hover)] text-[var(--forge-text)] border border-[var(--forge-border)]"
              >
                {s}
              </span>
            ))}
          </div>
        </div>

        {/* Stats */}
        <div className="px-4 mt-4">
          <h3 className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
            Stats
          </h3>
          <div className="grid grid-cols-2 gap-2">
            <StatCard
              icon={<MessageSquare className="w-3.5 h-3.5" />}
              label="Messages"
              value={String(convMessages.length)}
            />
            <StatCard
              icon={<Sparkles className="w-3.5 h-3.5" />}
              label="Responses"
              value={String(agentMessages.length)}
            />
            <StatCard
              icon={<Cpu className="w-3.5 h-3.5" />}
              label="Model"
              value={behavior.model.replace("Claude ", "")}
            />
            <StatCard
              icon={<Clock className="w-3.5 h-3.5" />}
              label="Last active"
              value={
                agent?.lastActive
                  ? formatRelative(agent.lastActive)
                  : "Never"
              }
            />
          </div>
        </div>

        {/* Quick actions */}
        <div className="px-4 mt-4 pb-4">
          <h3 className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
            Quick Actions
          </h3>
          <div className="space-y-1.5">
            {behavior.quickActions.map((action) => (
              <button
                key={action.label}
                onClick={() => onQuickAction?.(action)}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] text-left hover:bg-[var(--forge-hover)] hover:border-[var(--forge-text-muted)]/20 transition-colors group"
              >
                <span className="text-base shrink-0">{action.icon}</span>
                <span className="text-xs text-[var(--forge-text)] flex-1">
                  {action.label}
                </span>
                <ChevronRight className="w-3 h-3 text-[var(--forge-text-muted)] opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            ))}
          </div>
        </div>

        {/* Conversation info */}
        {conv && (
          <div className="px-4 pb-4 border-t border-[var(--forge-border)] mt-2 pt-3">
            <h3 className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
              Conversation
            </h3>
            <div className="space-y-1 text-xs text-[var(--forge-text-muted)]">
              <p>
                <span className="text-[var(--forge-text)]">
                  {userMessages.length}
                </span>{" "}
                messages sent
              </p>
              <p>
                <span className="text-[var(--forge-text)]">
                  {agentMessages.length}
                </span>{" "}
                responses received
              </p>
              {conv.createdAt && (
                <p>
                  Started{" "}
                  <span className="text-[var(--forge-text)]">
                    {new Date(conv.createdAt).toLocaleDateString()}
                  </span>
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Stat card ───────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-[var(--forge-bg)] border border-[var(--forge-border)]">
      <span className="text-[var(--forge-text-muted)]">{icon}</span>
      <div className="min-w-0">
        <p className="text-[10px] text-[var(--forge-text-muted)] uppercase tracking-wider leading-none">
          {label}
        </p>
        <p className="text-xs text-white font-medium mt-0.5 truncate">
          {value}
        </p>
      </div>
    </div>
  );
}

// ─── Thinking dots ───────────────────────────────────

function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1 h-1 rounded-full bg-[var(--forge-warning)]"
          style={{
            animation: "typing-bounce 1.4s infinite",
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
    </span>
  );
}

// ─── Helpers ─────────────────────────────────────────

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
