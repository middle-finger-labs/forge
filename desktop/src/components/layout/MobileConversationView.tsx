import { useCallback, useMemo, useState } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import type { MessageContent } from "@/types/message";
import type { PipelineRun } from "@/types/pipeline";
import { useAgentChat, AGENT_BEHAVIORS } from "@/hooks/useAgentChat";
import { useHaptics } from "@/hooks/useHaptics";
import { MessageList } from "@/components/conversation/MessageList";
import { MessageInput } from "@/components/conversation/MessageInput";
import {
  ArrowLeft,
  MoreVertical,
  Zap,
  Users,
  AlertTriangle,
  GitBranch,
  User,
  BellOff,
  Copy,
  Reply,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status colors ──────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  idle: "bg-[var(--forge-success)]",
  working: "bg-[var(--forge-warning)]",
  waiting: "bg-[var(--forge-warning)]",
  error: "bg-[var(--forge-error)]",
  offline: "bg-gray-600",
};

const STATUS_LABEL: Record<string, string> = {
  idle: "Online",
  working: "Working",
  waiting: "Waiting for input",
  error: "Error",
  offline: "Offline",
};

const AGENT_NAME_COLORS: Record<AgentRole, string> = {
  ba: "text-blue-400",
  researcher: "text-purple-400",
  architect: "text-amber-400",
  pm: "text-green-400",
  engineer: "text-cyan-400",
  qa: "text-pink-400",
  cto: "text-red-400",
};

const AGENT_COLORS: Record<AgentRole, string> = {
  ba: "bg-blue-500/10 border-blue-500/20",
  researcher: "bg-purple-500/10 border-purple-500/20",
  architect: "bg-amber-500/10 border-amber-500/20",
  pm: "bg-green-500/10 border-green-500/20",
  engineer: "bg-cyan-500/10 border-cyan-500/20",
  qa: "bg-pink-500/10 border-pink-500/20",
  cto: "bg-red-500/10 border-red-500/20",
};

// ─── Props ──────────────────────────────────────────

interface MobileConversationViewProps {
  conversationId: string;
  pipelineRuns: PipelineRun[];
  onBack: () => void;
  onOpenDAG: () => void;
  onOpenProfile: () => void;
}

// ─── Component ──────────────────────────────────────

export function MobileConversationView({
  conversationId,
  pipelineRuns,
  onBack,
  onOpenDAG,
  onOpenProfile,
}: MobileConversationViewProps) {
  const { conversations, messages, agents, addMessage } = useConversationStore();
  const { haptic } = useHaptics();
  const [menuOpen, setMenuOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; messageId: string } | null>(null);

  const conversation = conversations[conversationId];
  const channelMessages = messages[conversationId] ?? [];

  const isAgentDm = conversation?.type === "agent_dm";
  const isPipeline = conversation?.type === "pipeline";
  const agentRole = conversation?.agentRole;
  const agentInfo = agentRole ? AGENT_REGISTRY[agentRole] : undefined;
  const agentState = agentRole ? agents[agentRole] : undefined;

  const pipelineRun = conversation?.pipelineId
    ? pipelineRuns.find((r) => r.id === conversation.pipelineId)
    : undefined;

  // Agent chat hook
  const agentChat = useAgentChat(
    isAgentDm ? conversationId : undefined,
    agentRole
  );

  const isAgentThinking = agentChat?.isThinking ?? false;

  // Active agents for pipeline
  const activeAgents = useMemo(() => {
    if (!pipelineRun) return [];
    return pipelineRun.steps
      .filter((s) => s.status === "running")
      .map((s) => ({
        role: s.agentRole,
        info: AGENT_REGISTRY[s.agentRole],
        step: s.name,
      }));
  }, [pipelineRun]);

  // Send message
  const handleSend = useCallback(
    (content: MessageContent[]) => {
      haptic("medium");
      if (agentChat && content.length === 1 && content[0].type === "text") {
        agentChat.sendMessage(content[0].text);
      } else if (agentChat) {
        agentChat.sendContent(content);
      } else {
        addMessage({
          id: `local-${Date.now()}`,
          conversationId,
          author: { type: "user", userId: "me", name: "You" },
          content,
          createdAt: new Date().toISOString(),
        });
      }
    },
    [conversationId, addMessage, agentChat, haptic]
  );

  // Slash commands
  const handleSlashCommand = useCallback(
    (command: string, args: string) => {
      const now = new Date().toISOString();
      switch (command) {
        case "approve":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId,
            author: { type: "user", userId: "me", name: "You" },
            content: [{ type: "approval_response", approved: true, comment: args || undefined }],
            createdAt: now,
          });
          break;
        case "reject":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId,
            author: { type: "user", userId: "me", name: "You" },
            content: [{ type: "approval_response", approved: false, comment: args || "Changes requested" }],
            createdAt: now,
          });
          break;
        case "status":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId,
            author: { type: "system" },
            content: [{
              type: "text",
              text: pipelineRun
                ? `Pipeline "${pipelineRun.name}" is ${pipelineRun.status}.`
                : "No pipeline data available.",
            }],
            createdAt: now,
          });
          break;
      }
    },
    [conversationId, addMessage, pipelineRun]
  );

  if (!conversation) return null;

  const isPaused = pipelineRun?.status === "paused" || pipelineRun?.status === "awaiting_approval";
  const isFailed = pipelineRun?.status === "failed";

  return (
    <div className="flex flex-col h-[100dvh] bg-[var(--forge-channel)]">
      {/* Header */}
      <div className="flex items-center gap-2 px-2 shrink-0 border-b border-[var(--forge-border)] bg-[var(--forge-bg)] pt-[env(safe-area-inset-top)]">
        <button
          onClick={onBack}
          aria-label="Go back"
          className="p-2 text-[var(--forge-accent)]"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        {/* Conversation info */}
        <div className="flex-1 min-w-0 py-2">
          {isAgentDm && agentInfo ? (
            <button onClick={onOpenProfile} className="flex items-center gap-2 min-w-0">
              <div className="relative shrink-0">
                <span className="text-xl leading-none">{agentInfo.emoji}</span>
                {agentState && (
                  <span
                    className={cn(
                      "absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-[var(--forge-bg)]",
                      STATUS_DOT[agentState.status] ?? STATUS_DOT.offline,
                      agentState.status === "working" && "animate-pulse"
                    )}
                  />
                )}
              </div>
              <div className="min-w-0 text-left">
                <h2 className="text-sm font-semibold text-white truncate">
                  {agentInfo.displayName}
                </h2>
                <p className="text-[11px] text-[var(--forge-text-muted)] truncate">
                  {agentState?.status === "working"
                    ? agentState.currentTask ?? "Thinking..."
                    : STATUS_LABEL[agentState?.status ?? "offline"]}
                </p>
              </div>
            </button>
          ) : (
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white truncate">
                {isPipeline ? `# ${conversation.title}` : conversation.title}
              </h2>
              {isPipeline && pipelineRun && (
                <p className="text-[11px] text-[var(--forge-text-muted)] truncate">
                  {pipelineRun.steps.filter((s) => s.status === "completed").length}/{pipelineRun.steps.length} steps
                </p>
              )}
            </div>
          )}
        </div>

        {/* Menu button */}
        <div className="relative">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="More options"
            aria-expanded={menuOpen}
            className="p-2 text-[var(--forge-text-muted)]"
          >
            <MoreVertical className="w-5 h-5" />
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full z-50 mt-1 w-52 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl overflow-hidden">
                {isPipeline && (
                  <MenuButton
                    icon={GitBranch}
                    label="View Pipeline DAG"
                    onClick={() => { setMenuOpen(false); onOpenDAG(); }}
                  />
                )}
                {isAgentDm && (
                  <MenuButton
                    icon={User}
                    label="View Agent Profile"
                    onClick={() => { setMenuOpen(false); onOpenProfile(); }}
                  />
                )}
                <MenuButton
                  icon={BellOff}
                  label="Mute Notifications"
                  onClick={() => setMenuOpen(false)}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Pipeline status bars */}
      {isPipeline && activeAgents.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-1.5 bg-[var(--forge-accent)]/5 border-b border-[var(--forge-accent)]/10 shrink-0">
          <Users className="w-3 h-3 text-[var(--forge-accent)]" />
          <span className="text-[11px] text-[var(--forge-accent)] truncate">
            {activeAgents.map((a) => `${a.info.emoji} ${a.info.displayName}`).join(", ")}
            {activeAgents.length === 1 ? " is" : " are"} working
          </span>
        </div>
      )}

      {isPaused && (
        <div className="flex items-center gap-2 px-4 py-2 bg-[var(--forge-warning)]/5 border-b border-[var(--forge-warning)]/20 shrink-0">
          <Zap className="w-3.5 h-3.5 text-[var(--forge-warning)]" />
          <span className="text-xs text-[var(--forge-warning)] font-medium truncate">
            {pipelineRun?.status === "awaiting_approval"
              ? "Awaiting your approval"
              : "Pipeline paused"}
          </span>
          <button
            onClick={onOpenDAG}
            className="text-[10px] text-[var(--forge-warning)] underline ml-auto shrink-0"
          >
            View
          </button>
        </div>
      )}

      {isFailed && (
        <div className="flex items-center gap-2 px-4 py-2 bg-[var(--forge-error)]/5 border-b border-[var(--forge-error)]/20 shrink-0">
          <AlertTriangle className="w-3.5 h-3.5 text-[var(--forge-error)]" />
          <span className="text-xs text-[var(--forge-error)] font-medium">Pipeline failed</span>
          <button
            onClick={onOpenDAG}
            className="text-[10px] text-[var(--forge-error)] underline ml-auto shrink-0"
          >
            View
          </button>
        </div>
      )}

      {/* Messages */}
      {channelMessages.length === 0 && !isAgentThinking ? (
        <MobileEmptyState
          conversation={conversation}
          agentInfo={agentInfo}
          agentState={agentState}
          agentRole={agentRole}
          agentChat={agentChat}
        />
      ) : (
        <MessageList
          messages={channelMessages}
          thinkingIndicator={
            isAgentThinking && agentRole ? (
              <MobileThinkingIndicator
                agentRole={agentRole}
                currentTask={agentChat?.currentTask}
              />
            ) : undefined
          }
        />
      )}

      {/* Context menu for long-press */}
      {contextMenu && (
        <MessageContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* Input - full width, pinned to bottom */}
      <MessageInput
        conversationTitle={conversation.title}
        onSend={handleSend}
        onSlashCommand={handleSlashCommand}
        disabled={isAgentThinking}
        placeholder={
          isPaused
            ? "Type /approve or /reject..."
            : isAgentDm
              ? `Message ${agentInfo?.displayName ?? "agent"}...`
              : "Send a message..."
        }
      />
    </div>
  );
}

// ─── Menu Button ────────────────────────────────────

function MenuButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof GitBranch;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 w-full px-4 py-3 text-sm text-[var(--forge-text)] active:bg-[var(--forge-hover)] transition-colors"
    >
      <Icon className="w-4 h-4 text-[var(--forge-text-muted)]" />
      {label}
    </button>
  );
}

// ─── Message Context Menu ───────────────────────────

function MessageContextMenu({
  x,
  y,
  onClose,
}: {
  x: number;
  y: number;
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 z-50" onClick={onClose} />
      <div
        className="fixed z-50 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl overflow-hidden min-w-[160px]"
        style={{
          left: Math.min(x, window.innerWidth - 170),
          top: Math.min(y, window.innerHeight - 200),
        }}
      >
        <button
          onClick={onClose}
          className="flex items-center gap-3 w-full px-4 py-3 text-sm text-[var(--forge-text)] active:bg-[var(--forge-hover)]"
        >
          <Copy className="w-4 h-4 text-[var(--forge-text-muted)]" />
          Copy Text
        </button>
        <button
          onClick={onClose}
          className="flex items-center gap-3 w-full px-4 py-3 text-sm text-[var(--forge-text)] active:bg-[var(--forge-hover)]"
        >
          <Reply className="w-4 h-4 text-[var(--forge-text-muted)]" />
          Reply in Thread
        </button>
      </div>
    </>
  );
}

// ─── Mobile Thinking Indicator ──────────────────────

function MobileThinkingIndicator({
  agentRole,
  currentTask,
}: {
  agentRole: AgentRole;
  currentTask?: string;
}) {
  const info = AGENT_REGISTRY[agentRole];
  return (
    <div className="flex gap-3 px-4 mt-4">
      <div
        className={cn(
          "w-8 h-8 rounded-lg flex items-center justify-center text-base border shrink-0",
          AGENT_COLORS[agentRole]
        )}
      >
        {info.emoji}
      </div>
      <div className="min-w-0 flex-1">
        <span className={cn("font-semibold text-sm", AGENT_NAME_COLORS[agentRole])}>
          {info.displayName}
        </span>
        <div className="flex items-center gap-2 mt-0.5">
          <div className="flex items-center gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-2 h-2 rounded-full bg-[var(--forge-text-muted)]"
                style={{
                  animation: "typing-bounce 1.4s infinite",
                  animationDelay: `${i * 0.2}s`,
                }}
              />
            ))}
          </div>
          {currentTask && (
            <span className="text-xs text-[var(--forge-text-muted)] italic truncate">
              {currentTask}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Mobile Empty State ─────────────────────────────

function MobileEmptyState({
  conversation,
  agentInfo,
  agentState,
  agentRole,
  agentChat,
}: {
  conversation: { type: string; title: string };
  agentInfo?: { emoji: string; displayName: string };
  agentState?: { status: string; currentTask?: string };
  agentRole?: AgentRole;
  agentChat?: ReturnType<typeof useAgentChat>;
}) {
  const behavior = agentRole ? AGENT_BEHAVIORS[agentRole] : undefined;

  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
      {agentInfo && <span className="text-5xl mb-3">{agentInfo.emoji}</span>}
      <h3 className="text-lg font-semibold text-white mb-1">
        {conversation.type === "pipeline" ? `# ${conversation.title}` : conversation.title}
      </h3>
      <p className="text-sm text-[var(--forge-text-muted)] max-w-xs">
        {conversation.type === "agent_dm"
          ? `Send a message to start working with ${agentInfo?.displayName ?? "this agent"}.`
          : "Pipeline messages will appear here."}
      </p>
      {agentState && conversation.type === "agent_dm" && (
        <div className="flex items-center gap-2 mt-2 text-xs text-[var(--forge-text-muted)]">
          <span className={cn("w-2 h-2 rounded-full", STATUS_DOT[agentState.status] ?? STATUS_DOT.offline)} />
          <span>{STATUS_LABEL[agentState.status] ?? "Offline"}</span>
        </div>
      )}
      {/* Quick actions for agent DMs */}
      {conversation.type === "agent_dm" && behavior && agentChat && (
        <div className="mt-5 flex flex-col gap-2 w-full max-w-xs">
          <p className="text-[10px] text-[var(--forge-text-muted)] uppercase tracking-wider mb-0.5">
            Try asking
          </p>
          {behavior.quickActions.slice(0, 3).map((action) => (
            <button
              key={action.label}
              onClick={() => agentChat.sendMessage(action.prompt)}
              className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] text-left active:bg-[var(--forge-hover)] transition-colors"
            >
              <span className="text-base shrink-0">{action.icon}</span>
              <span className="text-xs text-[var(--forge-text)]">{action.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
