import { useConversationStore } from "@/stores/conversationStore";
import { AGENT_ROLES, AGENT_REGISTRY } from "@/types/agent";
import type { Agent, AgentRole } from "@/types/agent";

/** Returns all agents with their current status from the store */
export function useAgents() {
  const { agents } = useConversationStore();

  const allAgents: Agent[] = AGENT_ROLES.map((role) => {
    const stored = agents[role];
    if (stored) return stored;
    // Fallback for agents not yet loaded
    return {
      role,
      displayName: AGENT_REGISTRY[role].displayName,
      emoji: AGENT_REGISTRY[role].emoji,
      status: "offline" as const,
    };
  });

  const getAgent = (role: AgentRole): Agent | undefined =>
    allAgents.find((a) => a.role === role);

  return { agents: allAgents, getAgent };
}
