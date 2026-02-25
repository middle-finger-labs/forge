import { useCallback } from "react";
import { X, GitBranch, FileText, User, Settings, Code2 } from "lucide-react";
import { useLayoutStore } from "@/stores/layoutStore";
import { useConversationStore } from "@/stores/conversationStore";
import type { AgentRole } from "@/types/agent";
import type { PipelineRun } from "@/types/pipeline";
import { AgentProfile } from "@/components/agents/AgentProfile";
import { DAGMinimap } from "@/components/pipeline/DAGMinimap";
import { CostTracker } from "@/components/pipeline/CostTracker";
import { CodebaseExplorer } from "@/components/codebase/CodebaseExplorer";
import type { QuickAction } from "@/hooks/useAgentChat";
import { useAgentChat } from "@/hooks/useAgentChat";
import { cn } from "@/lib/utils";
import type { DetailPanelContent } from "@/stores/layoutStore";

const TABS: { id: DetailPanelContent; label: string; icon: typeof GitBranch }[] = [
  { id: "dag", label: "Pipeline", icon: GitBranch },
  { id: "files", label: "Files", icon: FileText },
  { id: "codebase", label: "Code", icon: Code2 },
  { id: "agent-profile", label: "Agent", icon: User },
  { id: "settings", label: "Settings", icon: Settings },
];

interface DetailPanelProps {
  pipelineRuns: PipelineRun[];
}

export function DetailPanel({ pipelineRuns }: DetailPanelProps) {
  const { detailPanelContent, openDetailPanel, closeDetailPanel } =
    useLayoutStore();
  const { activeConversationId, conversations } = useConversationStore();

  const active = activeConversationId
    ? conversations[activeConversationId]
    : undefined;

  const pipelineRun = active?.pipelineId
    ? pipelineRuns.find((r) => r.id === active.pipelineId)
    : undefined;

  const activeTab =
    detailPanelContent ?? (active?.type === "agent_dm" ? "agent-profile" : "dag");

  const agentRole = active?.agentRole as AgentRole | undefined;

  // Get agent chat hook for quick actions
  const agentChat = useAgentChat(
    active?.type === "agent_dm" ? activeConversationId ?? undefined : undefined,
    agentRole
  );

  const handleQuickAction = useCallback(
    (action: QuickAction) => {
      agentChat?.executeQuickAction(action);
    },
    [agentChat]
  );

  // Agent profile tab gets the full-width component (no outer padding)
  if (activeTab === "agent-profile" && agentRole) {
    return (
      <AgentProfile
        agentRole={agentRole}
        onClose={closeDetailPanel}
        onQuickAction={handleQuickAction}
      />
    );
  }

  return (
    <div className="flex flex-col h-full bg-[var(--forge-sidebar)] border-l border-[var(--forge-border)]">
      {/* Header */}
      <div className="flex items-center justify-between h-10 px-3 border-b border-[var(--forge-border)] shrink-0">
        <div className="flex items-center gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => openDetailPanel(tab.id)}
              className={cn(
                "px-2 py-1 text-xs rounded transition-colors",
                activeTab === tab.id
                  ? "bg-[var(--forge-hover)] text-white"
                  : "text-[var(--forge-text-muted)] hover:text-white"
              )}
            >
              <tab.icon className="w-3.5 h-3.5" />
            </button>
          ))}
        </div>
        <button
          onClick={closeDetailPanel}
          className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeTab === "dag" && (
          pipelineRun ? (
            <div className="space-y-4">
              <DAGMinimap
                pipelineRun={pipelineRun}
                onNodeClick={(_stepId, agentRole) => {
                  // Scroll to agent's messages or open their DM
                  const convId = `dm-${agentRole}`;
                  const { conversations } = useConversationStore.getState();
                  if (conversations[convId]) {
                    useConversationStore.getState().setActiveConversation(convId);
                  }
                }}
              />
              {pipelineRun.cost && (
                <CostTracker cost={pipelineRun.cost} />
              )}
            </div>
          ) : (
            <div className="text-sm text-[var(--forge-text-muted)]">
              <p>No pipeline selected.</p>
            </div>
          )
        )}
        {activeTab === "agent-profile" && !agentRole && (
          <div className="text-sm text-[var(--forge-text-muted)]">
            <p>Select an agent DM to view their profile.</p>
          </div>
        )}
        {activeTab === "files" && (
          <div className="text-sm text-[var(--forge-text-muted)]">
            <p className="font-medium text-white mb-2">Generated Files</p>
            <p>No files yet.</p>
          </div>
        )}
        {activeTab === "codebase" && (
          <div className="-m-3 h-[calc(100%+24px)]">
            <CodebaseExplorer />
          </div>
        )}
        {activeTab === "settings" && (
          <div className="text-sm text-[var(--forge-text-muted)]">
            <p className="font-medium text-white mb-2">Settings</p>
            <p>Configuration options will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}

