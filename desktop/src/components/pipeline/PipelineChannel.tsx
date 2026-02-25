import { useCallback, useMemo } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import type { MessageContent } from "@/types/message";
import type { PipelineRun } from "@/types/pipeline";
import type { StepStatus } from "@/types/pipeline";
import { MessageList } from "@/components/conversation/MessageList";
import { MessageInput } from "@/components/conversation/MessageInput";
import {
  Zap,
  Users,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Status colors ───────────────────────────────────

const STATUS_COLOR: Record<StepStatus, string> = {
  completed: "text-[var(--forge-success)]",
  running: "bg-[var(--forge-accent)]/20 text-[var(--forge-accent)]",
  pending: "text-[var(--forge-text-muted)]",
  failed: "text-[var(--forge-error)]",
  skipped: "text-[var(--forge-text-muted)] line-through",
};

const STATUS_ICON: Record<StepStatus, string> = {
  completed: "\u2705",
  running: "\u{1F504}",
  pending: "\u23F3",
  failed: "\u274C",
  skipped: "\u23ED\uFE0F",
};

// ─── Props ───────────────────────────────────────────

interface PipelineChannelProps {
  conversationId: string;
  pipelineRun?: PipelineRun;
}

// ─── PipelineChannel ─────────────────────────────────

export function PipelineChannel({
  conversationId,
  pipelineRun,
}: PipelineChannelProps) {
  const { conversations, messages, addMessage } = useConversationStore();
  const { openThread, openDetailPanel } = useLayoutStore();

  const conversation = conversations[conversationId];
  const channelMessages = messages[conversationId] ?? [];

  // Active agents: find which agents are currently working on this pipeline
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

  // Completed step count
  const progress = useMemo(() => {
    if (!pipelineRun) return null;
    const completed = pipelineRun.steps.filter(
      (s) => s.status === "completed"
    ).length;
    return { completed, total: pipelineRun.steps.length };
  }, [pipelineRun]);

  // Send a message as user intervention in the pipeline
  const handleSend = useCallback(
    (content: MessageContent[]) => {
      addMessage({
        id: `local-${Date.now()}`,
        conversationId,
        author: { type: "user", userId: "me", name: "You" },
        content,
        createdAt: new Date().toISOString(),
      });
    },
    [conversationId, addMessage]
  );

  // Slash commands for pipeline channels
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
            content: [
              {
                type: "approval_response",
                approved: false,
                comment: args || "Changes requested",
              },
            ],
            createdAt: now,
          });
          break;

        case "pause":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId,
            author: { type: "system" },
            content: [
              {
                type: "pipeline_event",
                event: "pipeline_paused",
                details: { reason: args || "Paused by user" },
              },
            ],
            createdAt: now,
          });
          break;

        case "resume":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId,
            author: { type: "system" },
            content: [
              {
                type: "pipeline_event",
                event: "pipeline_resumed",
                details: {},
              },
            ],
            createdAt: now,
          });
          break;

        case "status":
          addMessage({
            id: `local-${Date.now()}`,
            conversationId,
            author: { type: "system" },
            content: [
              {
                type: "text",
                text: pipelineRun
                  ? `Pipeline "${pipelineRun.name}" is ${pipelineRun.status}. ${progress?.completed}/${progress?.total} steps completed.`
                  : "No pipeline data available.",
              },
            ],
            createdAt: now,
          });
          break;

        case "cost":
          if (pipelineRun?.cost) {
            addMessage({
              id: `local-${Date.now()}`,
              conversationId,
              author: { type: "system" },
              content: [
                {
                  type: "cost_update",
                  totalCost: pipelineRun.cost.total,
                  breakdown: Object.fromEntries(
                    Object.entries(pipelineRun.cost.perAgent).map(
                      ([k, v]) => [AGENT_REGISTRY[k as AgentRole]?.displayName ?? k, v ?? 0]
                    )
                  ),
                },
              ],
              createdAt: now,
            });
          }
          break;
      }
    },
    [conversationId, addMessage, pipelineRun, progress]
  );

  // Open thread handler
  const handleOpenThread = useCallback(
    (messageId: string) => {
      openThread(messageId, conversationId);
    },
    [conversationId, openThread]
  );

  if (!conversation) return null;

  // Pipeline status info
  const isPaused =
    pipelineRun?.status === "paused" ||
    pipelineRun?.status === "awaiting_approval";
  const isFailed = pipelineRun?.status === "failed";

  return (
    <div className="flex flex-1 flex-col min-h-0 bg-[var(--forge-channel)]">
      {/* Pipeline conversation header */}
      <div className="flex items-center px-5 py-2.5 border-b border-[var(--forge-border)] shrink-0 gap-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-white shrink-0">
            # {conversation.title}
          </h2>

          {/* Inline step progress */}
          {pipelineRun && (
            <div className="flex items-center gap-1 overflow-x-auto min-w-0 flex-1">
              {pipelineRun.steps.map((step, i) => (
                <span key={step.id} className="flex items-center gap-0.5 shrink-0">
                  <span
                    className={cn(
                      "text-[11px] px-1.5 py-0.5 rounded font-medium",
                      STATUS_COLOR[step.status]
                    )}
                  >
                    {step.name} {STATUS_ICON[step.status]}
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
      </div>

      {/* Active agents bar */}
      {activeAgents.length > 0 && (
        <div className="flex items-center gap-2 px-5 py-1.5 bg-[var(--forge-accent)]/5 border-b border-[var(--forge-accent)]/10 shrink-0">
          <Users className="w-3 h-3 text-[var(--forge-accent)]" />
          <span className="text-[11px] text-[var(--forge-accent)]">
            {activeAgents.map((a) => `${a.info.emoji} ${a.info.displayName}`).join(", ")}
            {activeAgents.length === 1 ? " is" : " are"} working
          </span>
          <span className="text-[10px] text-[var(--forge-text-muted)] ml-auto">
            {activeAgents.map((a) => a.step).join(" | ")}
          </span>
        </div>
      )}

      {/* Approval / pause banner */}
      {isPaused && (
        <div className="flex items-center gap-2 px-5 py-2 bg-[var(--forge-warning)]/5 border-b border-[var(--forge-warning)]/20 shrink-0">
          <Zap className="w-3.5 h-3.5 text-[var(--forge-warning)]" />
          <span className="text-xs text-[var(--forge-warning)] font-medium">
            {pipelineRun?.status === "awaiting_approval"
              ? "Pipeline paused — awaiting your approval"
              : "Pipeline paused"}
          </span>
          {pipelineRun?.status === "awaiting_approval" && (
            <button
              onClick={() => openDetailPanel("dag")}
              className="text-[10px] text-[var(--forge-warning)] underline ml-auto hover:opacity-80"
            >
              View details
            </button>
          )}
        </div>
      )}

      {isFailed && (
        <div className="flex items-center gap-2 px-5 py-2 bg-[var(--forge-error)]/5 border-b border-[var(--forge-error)]/20 shrink-0">
          <AlertTriangle className="w-3.5 h-3.5 text-[var(--forge-error)]" />
          <span className="text-xs text-[var(--forge-error)] font-medium">
            Pipeline failed
          </span>
          <button
            onClick={() => openDetailPanel("dag")}
            className="text-[10px] text-[var(--forge-error)] underline ml-auto hover:opacity-80"
          >
            View details
          </button>
        </div>
      )}

      {/* Messages */}
      {channelMessages.length === 0 ? (
        <PipelineEmptyState title={conversation.title} />
      ) : (
        <MessageList
          messages={channelMessages}
          onOpenThread={handleOpenThread}
        />
      )}

      {/* Input — always enabled for user intervention */}
      <MessageInput
        conversationTitle={conversation.title}
        onSend={handleSend}
        onSlashCommand={handleSlashCommand}
        placeholder={
          isPaused
            ? "Type /approve or /reject, or send a message..."
            : "Send a message to the team, @mention an agent, or use /commands..."
        }
      />
    </div>
  );
}

// ─── Pipeline empty state ────────────────────────────

function PipelineEmptyState({ title }: { title: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
      <Zap className="w-12 h-12 text-[var(--forge-accent)] opacity-40 mb-4" />
      <h3 className="text-lg font-semibold text-white mb-1.5">
        # {title}
      </h3>
      <p className="text-sm text-[var(--forge-text-muted)] max-w-sm mb-6">
        This is the beginning of the pipeline channel. Your agent team will
        post updates here as they work.
      </p>
      <div className="flex flex-col gap-2 text-xs text-[var(--forge-text-muted)]">
        <span>
          <kbd className="font-mono bg-[var(--forge-hover)] px-1.5 py-0.5 rounded">
            /approve
          </kbd>{" "}
          or{" "}
          <kbd className="font-mono bg-[var(--forge-hover)] px-1.5 py-0.5 rounded">
            /reject
          </kbd>{" "}
          to respond to approvals
        </span>
        <span>
          <kbd className="font-mono bg-[var(--forge-hover)] px-1.5 py-0.5 rounded">
            @agent
          </kbd>{" "}
          to direct a message to a specific agent
        </span>
        <span>
          <kbd className="font-mono bg-[var(--forge-hover)] px-1.5 py-0.5 rounded">
            /status
          </kbd>{" "}
          to check pipeline progress
        </span>
      </div>
    </div>
  );
}
