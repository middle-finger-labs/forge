import { useCallback, useMemo } from "react";
import { useConversationStore } from "@/stores/conversationStore";
import { getForgeAPI } from "@/services/api";
import type { AgentRole, AgentStatus } from "@/types/agent";
import type { Message, MessageContent } from "@/types/message";
import { AGENT_REGISTRY } from "@/types/agent";

// ─── Agent-specific descriptions & quick actions ─────

export interface AgentBehavior {
  role: AgentRole;
  description: string;
  specialties: string[];
  model: string;
  quickActions: QuickAction[];
}

export interface QuickAction {
  label: string;
  prompt: string;
  icon: string;
}

export const AGENT_BEHAVIORS: Record<AgentRole, AgentBehavior> = {
  ba: {
    role: "ba",
    description:
      "Gathers requirements, writes user stories, and maps stakeholder needs into actionable specs.",
    specialties: [
      "Requirements gathering",
      "User story mapping",
      "Stakeholder analysis",
      "Acceptance criteria",
    ],
    model: "Claude Sonnet 4",
    quickActions: [
      {
        label: "Write user stories",
        prompt: "Write user stories for the current feature we're working on.",
        icon: "\u{1F4DD}",
      },
      {
        label: "Define requirements",
        prompt:
          "Help me define the requirements for a new feature. Ask me questions to clarify scope.",
        icon: "\u{1F4CB}",
      },
      {
        label: "Acceptance criteria",
        prompt:
          "Generate acceptance criteria for the current set of user stories.",
        icon: "\u2705",
      },
    ],
  },
  researcher: {
    role: "researcher",
    description:
      "Conducts deep research on technologies, markets, and competitors to inform product decisions.",
    specialties: [
      "Market research",
      "Competitor analysis",
      "Technology assessment",
      "Trend analysis",
    ],
    model: "Claude Sonnet 4",
    quickActions: [
      {
        label: "Research topic",
        prompt:
          "I need research on a topic. Help me understand the current landscape.",
        icon: "\u{1F50D}",
      },
      {
        label: "Competitor analysis",
        prompt:
          "Conduct a competitor analysis for our product space. What are the key players doing?",
        icon: "\u{1F4CA}",
      },
      {
        label: "Tech assessment",
        prompt:
          "Evaluate technology options for our next feature. Compare trade-offs.",
        icon: "\u2696\uFE0F",
      },
    ],
  },
  architect: {
    role: "architect",
    description:
      "Designs system architecture, makes technology decisions, and ensures scalable, maintainable solutions.",
    specialties: [
      "System design",
      "API design",
      "Database modeling",
      "Infrastructure planning",
    ],
    model: "Claude Sonnet 4",
    quickActions: [
      {
        label: "Design system",
        prompt:
          "Help me design the architecture for a new system component. I'll describe the requirements.",
        icon: "\u{1F3D7}\uFE0F",
      },
      {
        label: "Review architecture",
        prompt:
          "Review the current architecture and suggest improvements for scalability.",
        icon: "\u{1F50E}",
      },
      {
        label: "API design",
        prompt:
          "Design REST API endpoints for a new feature. Help me define the contract.",
        icon: "\u{1F517}",
      },
    ],
  },
  pm: {
    role: "pm",
    description:
      "Manages project timelines, tracks progress, coordinates between agents, and ensures delivery.",
    specialties: [
      "Project planning",
      "Sprint management",
      "Risk assessment",
      "Stakeholder communication",
    ],
    model: "Claude Sonnet 4",
    quickActions: [
      {
        label: "Create plan",
        prompt:
          "Help me create a project plan. What are the key milestones and tasks?",
        icon: "\u{1F4C5}",
      },
      {
        label: "Status report",
        prompt:
          "Generate a status report for the current sprint. Summarize progress and blockers.",
        icon: "\u{1F4CA}",
      },
      {
        label: "Risk assessment",
        prompt:
          "Identify potential risks for the current project and suggest mitigation strategies.",
        icon: "\u26A0\uFE0F",
      },
    ],
  },
  engineer: {
    role: "engineer",
    description:
      "Writes production code, implements features, fixes bugs, and maintains code quality.",
    specialties: [
      "Feature implementation",
      "Bug fixing",
      "Code refactoring",
      "Performance optimization",
    ],
    model: "Claude Sonnet 4",
    quickActions: [
      {
        label: "Implement feature",
        prompt:
          "I need to implement a new feature. Let me describe what I need built.",
        icon: "\u{1F4BB}",
      },
      {
        label: "Fix bug",
        prompt:
          "I have a bug that needs fixing. Let me describe the symptoms and expected behavior.",
        icon: "\u{1F41B}",
      },
      {
        label: "Code review",
        prompt:
          "Review this code for potential issues, bugs, and improvements.",
        icon: "\u{1F50D}",
      },
    ],
  },
  qa: {
    role: "qa",
    description:
      "Creates test plans, writes automated tests, tracks bugs, and ensures quality standards.",
    specialties: [
      "Test planning",
      "Automated testing",
      "Bug tracking",
      "Quality metrics",
    ],
    model: "Claude Sonnet 4",
    quickActions: [
      {
        label: "Write tests",
        prompt:
          "Write test cases for the current feature. Cover happy paths and edge cases.",
        icon: "\u{1F9EA}",
      },
      {
        label: "Test plan",
        prompt:
          "Create a comprehensive test plan for the current sprint deliverables.",
        icon: "\u{1F4DD}",
      },
      {
        label: "Bug report",
        prompt:
          "Help me document a bug with proper reproduction steps and expected behavior.",
        icon: "\u{1F41E}",
      },
    ],
  },
  cto: {
    role: "cto",
    description:
      "Provides strategic technical leadership, reviews critical decisions, and oversees the agent team.",
    specialties: [
      "Technical strategy",
      "Architecture review",
      "Team coordination",
      "Decision making",
    ],
    model: "Claude Opus 4",
    quickActions: [
      {
        label: "Strategic review",
        prompt:
          "Review our current technical strategy. What should we prioritize?",
        icon: "\u{1F3AF}",
      },
      {
        label: "Decision help",
        prompt:
          "I need help making a critical technical decision. Let me lay out the options.",
        icon: "\u{1F914}",
      },
      {
        label: "Team sync",
        prompt:
          "Summarize what each agent has been working on and identify any coordination issues.",
        icon: "\u{1F91D}",
      },
    ],
  },
};

// ─── Hook return type ────────────────────────────────

export interface AgentChatState {
  /** Messages for this agent's conversation */
  messages: Message[];
  /** The agent's current status */
  agentStatus: AgentStatus;
  /** The agent's current task description */
  currentTask: string | undefined;
  /** Whether the agent is currently thinking/working */
  isThinking: boolean;
  /** Send a text message to the agent */
  sendMessage: (text: string) => Promise<void>;
  /** Send structured content to the agent */
  sendContent: (content: MessageContent[]) => Promise<void>;
  /** Execute a quick action */
  executeQuickAction: (action: QuickAction) => Promise<void>;
  /** Agent behavior config */
  behavior: AgentBehavior;
}

// ─── useAgentChat ────────────────────────────────────

export function useAgentChat(
  conversationId: string | undefined,
  agentRole: AgentRole | undefined
): AgentChatState | null {
  const { messages: allMessages, agents, addMessage } =
    useConversationStore();

  const behavior = agentRole ? AGENT_BEHAVIORS[agentRole] : undefined;
  const agent = agentRole ? agents[agentRole] : undefined;
  const agentInfo = agentRole ? AGENT_REGISTRY[agentRole] : undefined;

  const messages = useMemo(
    () => (conversationId ? (allMessages[conversationId] ?? []) : []),
    [allMessages, conversationId]
  );

  // Send a text message with optimistic update
  const sendMessage = useCallback(
    async (text: string) => {
      if (!conversationId || !text.trim()) return;

      // Optimistic local insert
      const optimisticMsg: Message = {
        id: `optimistic-${Date.now()}`,
        conversationId,
        author: { type: "user", userId: "me", name: "You" },
        content: [{ type: "text", text: text.trim() }],
        createdAt: new Date().toISOString(),
      };
      addMessage(optimisticMsg);

      // Dispatch to API
      try {
        const api = await getForgeAPI();
        await api.sendMessage(conversationId, [
          { type: "text", text: text.trim() },
        ]);
      } catch (err) {
        // On failure, add an error system message
        addMessage({
          id: `error-${Date.now()}`,
          conversationId,
          author: { type: "system" },
          content: [
            {
              type: "text",
              text: `Failed to send message: ${err instanceof Error ? err.message : "Unknown error"}`,
            },
          ],
          createdAt: new Date().toISOString(),
        });
      }
    },
    [conversationId, addMessage]
  );

  // Send structured content
  const sendContent = useCallback(
    async (content: MessageContent[]) => {
      if (!conversationId) return;

      const optimisticMsg: Message = {
        id: `optimistic-${Date.now()}`,
        conversationId,
        author: { type: "user", userId: "me", name: "You" },
        content,
        createdAt: new Date().toISOString(),
      };
      addMessage(optimisticMsg);

      try {
        const api = await getForgeAPI();
        await api.sendMessage(conversationId, content);
      } catch (err) {
        addMessage({
          id: `error-${Date.now()}`,
          conversationId,
          author: { type: "system" },
          content: [
            {
              type: "text",
              text: `Failed to send message: ${err instanceof Error ? err.message : "Unknown error"}`,
            },
          ],
          createdAt: new Date().toISOString(),
        });
      }
    },
    [conversationId, addMessage]
  );

  // Execute a quick action
  const executeQuickAction = useCallback(
    async (action: QuickAction) => {
      await sendMessage(action.prompt);
    },
    [sendMessage]
  );

  if (!conversationId || !agentRole || !behavior || !agentInfo) {
    return null;
  }

  return {
    messages,
    agentStatus: agent?.status ?? "offline",
    currentTask: agent?.currentTask,
    isThinking: agent?.status === "working",
    sendMessage,
    sendContent,
    executeQuickAction,
    behavior,
  };
}
