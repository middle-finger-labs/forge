import { useCallback } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import type { MessageContent } from "@/types/message";
import type { PipelineRun } from "@/types/pipeline";
import type { StepStatus } from "@/types/pipeline";
import { useAgentChat } from "@/hooks/useAgentChat";
import { AGENT_BEHAVIORS } from "@/hooks/useAgentChat";
import { MessageList } from "./MessageList";
import { MessageInput } from "./MessageInput";
import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status dot colors ──────────────────────────────────

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

const STEP_STATUS_ICON: Record<StepStatus, string> = {
  completed: "\u2705",
  running: "\u{1F504}",
  pending: "\u23F3",
  failed: "\u274C",
  skipped: "\u23ED\uFE0F",
};

// ─── Agent name colors (for thinking indicator) ─────────

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

// ─── Props ──────────────────────────────────────────────

interface ConversationViewProps {
  pipelineRuns: PipelineRun[];
}

// ─── ConversationView ───────────────────────────────────

export function ConversationView({ pipelineRuns }: ConversationViewProps) {
  const {
    activeConversationId,
    conversations,
    messages,
    agents,
    addMessage,
  } = useConversationStore();

  const { openThread, openDetailPanel } = useLayoutStore();

  const active = activeConversationId
    ? conversations[activeConversationId]
    : undefined;

  const activeMessages = activeConversationId
    ? (messages[activeConversationId] ?? [])
    : [];

  // Agent info for DMs
  const agentRole = active?.agentRole;
  const agentInfo = agentRole ? AGENT_REGISTRY[agentRole] : undefined;
  const agentState = agentRole ? agents[agentRole] : undefined;

  // Agent chat hook for DM conversations
  const agentChat = useAgentChat(
    active?.type === "agent_dm" ? activeConversationId ?? undefined : undefined,
    agentRole
  );

  // Pipeline run for pipeline channels
  const pipelineRun = active?.pipelineId
    ? pipelineRuns.find((r) => r.id === active.pipelineId)
    : undefined;

  // Send message handler — uses agentChat for DMs, local for others
  const handleSend = useCallback(
    (content: MessageContent[]) => {
      if (!activeConversationId) return;

      if (agentChat && content.length === 1 && content[0].type === "text") {
        // Agent DM: use the hook for optimistic + API dispatch
        agentChat.sendMessage(content[0].text);
      } else if (agentChat) {
        agentChat.sendContent(content);
      } else {
        // Non-agent: local message only
        addMessage({
          id: `local-${Date.now()}`,
          conversationId: activeConversationId,
          author: { type: "user", userId: "me", name: "You" },
          content,
          createdAt: new Date().toISOString(),
        });
      }
    },
    [activeConversationId, addMessage, agentChat]
  );

  // Slash command handler
  const handleSlashCommand = useCallback(
    (command: string, args: string) => {
      if (!activeConversationId) return;

      switch (command) {
        case "pipeline":
        case "new":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId: activeConversationId,
            author: { type: "system" },
            content: [
              {
                type: "pipeline_event",
                event: "pipeline_requested",
                details: { spec: args },
              },
            ],
            createdAt: new Date().toISOString(),
          });
          break;

        case "approve":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId: activeConversationId,
            author: { type: "user", userId: "me", name: "You" },
            content: [{ type: "approval_response", approved: true }],
            createdAt: new Date().toISOString(),
          });
          break;

        case "reject":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId: activeConversationId,
            author: { type: "user", userId: "me", name: "You" },
            content: [
              {
                type: "approval_response",
                approved: false,
                comment: args || undefined,
              },
            ],
            createdAt: new Date().toISOString(),
          });
          break;

        case "status":
        case "cost":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId: activeConversationId,
            author: { type: "system" },
            content: [
              {
                type: "text",
                text: `/${command} — This will be connected to the backend.`,
              },
            ],
            createdAt: new Date().toISOString(),
          });
          break;
      }
    },
    [activeConversationId, addMessage]
  );

  // Open thread handler
  const handleOpenThread = useCallback(
    (messageId: string) => {
      if (!activeConversationId) return;
      openThread(messageId, activeConversationId);
    },
    [activeConversationId, openThread]
  );

  // ─── No conversation selected ─────────────────────────
  if (!active) {
    return (
      <div className="flex flex-1 items-center justify-center bg-[var(--forge-bg)]">
        <div className="text-center max-w-md">
          <Zap className="w-12 h-12 mx-auto mb-4 text-[var(--forge-accent)] opacity-60" />
          <h2 className="text-xl font-semibold text-white mb-2">
            Welcome to Forge
          </h2>
          <p className="text-sm text-[var(--forge-text-muted)] mb-6">
            Chat with your agents or start a pipeline run. Your AI team is
            ready to work.
          </p>
          <div className="flex flex-col items-center gap-2 text-xs text-[var(--forge-text-muted)]">
            <KeyHint keys={["\u2318", "K"]} label="Quick switcher" />
            <KeyHint keys={["\u2318", "N"]} label="New pipeline" />
            <KeyHint keys={["\u2318", "1-7"]} label="Jump to agent" />
          </div>
        </div>
      </div>
    );
  }

  // ─── Conversation view ────────────────────────────────
  const isAgentDm = active.type === "agent_dm";
  const isAgentThinking = agentChat?.isThinking ?? false;

  return (
    <div className="flex flex-1 flex-col min-h-0 bg-[var(--forge-channel)]">
      {/* Conversation toolbar */}
      <ConversationToolbar
        conversation={active}
        agentInfo={agentInfo}
        agentState={agentState}
        pipelineRun={pipelineRun}
        onOpenProfile={
          isAgentDm ? () => openDetailPanel("agent-profile") : undefined
        }
      />

      {/* Messages + thinking indicator */}
      {activeMessages.length === 0 && !isAgentThinking ? (
        <EmptyState
          title={active.title}
          type={active.type}
          agentEmoji={agentInfo?.emoji}
          agentStatus={agentState?.status}
          agentRole={agentRole}
          onQuickAction={
            agentChat
              ? (prompt: string) => agentChat.sendMessage(prompt)
              : undefined
          }
        />
      ) : (
        <MessageList
          messages={activeMessages}
          onOpenThread={handleOpenThread}
          thinkingIndicator={
            isAgentThinking && agentRole ? (
              <ThinkingIndicator
                agentRole={agentRole}
                currentTask={agentChat?.currentTask}
              />
            ) : undefined
          }
        />
      )}

      {/* Input */}
      <MessageInput
        conversationTitle={active.title}
        onSend={handleSend}
        onSlashCommand={handleSlashCommand}
        disabled={isAgentThinking}
      />
    </div>
  );
}

// ─── Thinking indicator ─────────────────────────────────

function ThinkingIndicator({
  agentRole,
  currentTask,
}: {
  agentRole: AgentRole;
  currentTask?: string;
}) {
  const info = AGENT_REGISTRY[agentRole];

  return (
    <div className="flex gap-3 px-5 mt-4">
      {/* Agent avatar */}
      <div className="shrink-0 w-9 mt-0.5">
        <div
          className={cn(
            "w-9 h-9 rounded-lg flex items-center justify-center text-lg border",
            AGENT_COLORS[agentRole]
          )}
        >
          {info.emoji}
        </div>
      </div>

      {/* Thinking content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 mb-1">
          <span
            className={cn(
              "font-semibold text-sm",
              AGENT_NAME_COLORS[agentRole]
            )}
          >
            {info.displayName}
          </span>
        </div>
        <div className="flex items-center gap-2">
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
            <span className="text-xs text-[var(--forge-text-muted)] italic">
              {currentTask}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Conversation toolbar ───────────────────────────────

function ConversationToolbar({
  conversation,
  agentInfo,
  agentState,
  pipelineRun,
  onOpenProfile,
}: {
  conversation: {
    type: string;
    title: string;
    participants: { type: string }[];
  };
  agentInfo?: { emoji: string; displayName: string };
  agentState?: { status: string; currentTask?: string };
  pipelineRun?: PipelineRun;
  onOpenProfile?: () => void;
}) {
  return (
    <div className="flex items-center px-5 py-2.5 border-b border-[var(--forge-border)] shrink-0 gap-3">
      {/* Agent DM: show agent profile */}
      {conversation.type === "agent_dm" && agentInfo && (
        <button
          onClick={onOpenProfile}
          className="flex items-center gap-3 min-w-0 hover:opacity-80 transition-opacity"
        >
          <div className="relative">
            <span className="text-2xl">{agentInfo.emoji}</span>
            {agentState && (
              <span
                className={cn(
                  "absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-[var(--forge-channel)]",
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
            <p className="text-xs text-[var(--forge-text-muted)] truncate">
              {agentState?.status === "working" ? (
                <span className="flex items-center gap-1.5">
                  <ToolbarThinkingDots />
                  <span>
                    {agentState.currentTask ?? "Thinking..."}
                  </span>
                </span>
              ) : (
                (agentState?.currentTask ??
                  STATUS_LABEL[agentState?.status ?? "offline"])
              )}
            </p>
          </div>
        </button>
      )}

      {/* Pipeline: show status bar */}
      {conversation.type === "pipeline" && (
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-white shrink-0">
            # {conversation.title}
          </h2>
          {pipelineRun && (
            <div className="flex items-center gap-1 overflow-x-auto min-w-0 flex-1">
              {pipelineRun.steps.map((step, i) => (
                <span key={step.id} className="flex items-center gap-0.5 shrink-0">
                  <span
                    className={cn(
                      "text-[11px] px-1.5 py-0.5 rounded font-medium",
                      step.status === "running" &&
                        "bg-[var(--forge-accent)]/20 text-[var(--forge-accent)]",
                      step.status === "completed" && "text-[var(--forge-success)]",
                      step.status === "failed" && "text-[var(--forge-error)]",
                      step.status === "pending" && "text-[var(--forge-text-muted)]",
                      step.status === "skipped" &&
                        "text-[var(--forge-text-muted)] line-through"
                    )}
                  >
                    {step.name} {STEP_STATUS_ICON[step.status]}
                  </span>
                  {i < pipelineRun.steps.length - 1 && (
                    <span className="text-[var(--forge-text-muted)] text-[10px] mx-0.5">
                      {"\u2192"}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}
          <span className="text-xs text-[var(--forge-text-muted)] shrink-0 ml-auto">
            {conversation.participants.length} members
          </span>
        </div>
      )}

      {/* General conversation */}
      {conversation.type === "general" && (
        <h2 className="text-sm font-semibold text-white truncate">
          {conversation.title}
        </h2>
      )}
    </div>
  );
}

// ─── Toolbar thinking dots ──────────────────────────────

function ToolbarThinkingDots() {
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

// ─── Empty state ────────────────────────────────────────

function EmptyState({
  title,
  type,
  agentEmoji,
  agentStatus,
  agentRole,
  onQuickAction,
}: {
  title: string;
  type: string;
  agentEmoji?: string;
  agentStatus?: string;
  agentRole?: AgentRole;
  onQuickAction?: (prompt: string) => void;
}) {
  const behavior = agentRole ? AGENT_BEHAVIORS[agentRole] : undefined;

  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
      {agentEmoji && <span className="text-6xl mb-4">{agentEmoji}</span>}
      <h3 className="text-lg font-semibold text-white mb-1.5">
        {type === "pipeline" ? `# ${title}` : title}
      </h3>
      <p className="text-sm text-[var(--forge-text-muted)] max-w-sm">
        {type === "agent_dm"
          ? `Send a message to start working with ${title}.`
          : `This is the beginning of the ${title} pipeline channel.`}
      </p>
      {type === "agent_dm" && agentStatus && (
        <div className="flex items-center gap-2 mt-3 text-xs text-[var(--forge-text-muted)]">
          <span
            className={cn(
              "w-2 h-2 rounded-full",
              STATUS_DOT[agentStatus] ?? STATUS_DOT.offline
            )}
          />
          <span>{STATUS_LABEL[agentStatus] ?? "Offline"}</span>
        </div>
      )}

      {/* Quick action suggestions for agent DMs */}
      {type === "agent_dm" && behavior && onQuickAction && (
        <div className="mt-6 flex flex-col gap-2 max-w-xs w-full">
          <p className="text-[10px] text-[var(--forge-text-muted)] uppercase tracking-wider mb-1">
            Try asking
          </p>
          {behavior.quickActions.map((action) => (
            <button
              key={action.label}
              onClick={() => onQuickAction(action.prompt)}
              className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] text-left hover:bg-[var(--forge-hover)] hover:border-[var(--forge-text-muted)]/30 transition-colors group"
            >
              <span className="text-base shrink-0">{action.icon}</span>
              <span className="text-xs text-[var(--forge-text)]">
                {action.label}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Loading skeleton ───────────────────────────────────

export function ConversationSkeleton() {
  return (
    <div className="flex flex-1 flex-col min-h-0 bg-[var(--forge-channel)]">
      {/* Toolbar skeleton */}
      <div className="flex items-center px-5 py-2.5 border-b border-[var(--forge-border)] shrink-0 gap-3">
        <div className="w-8 h-8 rounded-lg bg-[var(--forge-hover)] animate-pulse" />
        <div className="space-y-1.5">
          <div className="w-24 h-3.5 rounded bg-[var(--forge-hover)] animate-pulse" />
          <div className="w-16 h-2.5 rounded bg-[var(--forge-hover)] animate-pulse" />
        </div>
      </div>

      {/* Messages skeleton */}
      <div className="flex-1 p-5 space-y-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex gap-3">
            <div className="w-9 h-9 rounded-lg bg-[var(--forge-hover)] animate-pulse shrink-0" />
            <div className="space-y-2 flex-1">
              <div className="flex gap-2">
                <div className="w-20 h-3.5 rounded bg-[var(--forge-hover)] animate-pulse" />
                <div className="w-12 h-2.5 rounded bg-[var(--forge-hover)] animate-pulse" />
              </div>
              <div className="w-3/4 h-3 rounded bg-[var(--forge-hover)] animate-pulse" />
              <div className="w-1/2 h-3 rounded bg-[var(--forge-hover)] animate-pulse" />
            </div>
          </div>
        ))}
      </div>

      {/* Input skeleton */}
      <div className="px-4 pb-4 pt-2 shrink-0">
        <div className="h-12 rounded-lg bg-[var(--forge-bg)] border border-[var(--forge-border)] animate-pulse" />
      </div>
    </div>
  );
}

// ─── Key hint ───────────────────────────────────────────

function KeyHint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span>
      {keys.map((k, i) => (
        <kbd
          key={i}
          className="font-mono bg-[var(--forge-hover)] px-1.5 py-0.5 rounded text-[var(--forge-text)] mx-0.5"
        >
          {k}
        </kbd>
      ))}
      {" "}
      {label}
    </span>
  );
}
