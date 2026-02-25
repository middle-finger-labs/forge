import { create } from "zustand";
import type { Conversation } from "@/types/conversation";
import type { Message } from "@/types/message";
import type { Agent, AgentRole, AgentStatus } from "@/types/agent";

interface ConversationStore {
  // State (Records for Zustand immutability, semantically equivalent to Map)
  conversations: Record<string, Conversation>;
  messages: Record<string, Message[]>;
  agents: Record<AgentRole, Agent>;
  activeConversationId: string | null;

  // Actions
  setActiveConversation: (id: string | null) => void;
  addMessage: (msg: Message) => void;
  setMessages: (conversationId: string, messages: Message[]) => void;
  markRead: (conversationId: string) => void;
  updateAgentStatus: (role: AgentRole, status: AgentStatus, currentTask?: string) => void;
  addConversation: (conversation: Conversation) => void;

  // Bulk setters for initialization
  setConversations: (conversations: Conversation[]) => void;
  setAgents: (agents: Agent[]) => void;
}

export const useConversationStore = create<ConversationStore>((set, get) => ({
  conversations: {},
  messages: {},
  agents: {} as Record<AgentRole, Agent>,
  activeConversationId: null,

  setActiveConversation: (id) => {
    set({ activeConversationId: id });
    // Auto-mark read when switching
    if (id) {
      get().markRead(id);
    }
  },

  addMessage: (msg) =>
    set((state) => {
      const convId = msg.conversationId;
      const existing = state.messages[convId] ?? [];

      // Update lastMessage on the conversation
      const conv = state.conversations[convId];
      const updatedConv = conv
        ? {
            ...conv,
            lastMessage: msg,
            updatedAt: msg.createdAt,
            // Increment unread if not the active conversation
            unreadCount:
              state.activeConversationId === convId
                ? conv.unreadCount
                : conv.unreadCount + 1,
          }
        : undefined;

      return {
        messages: {
          ...state.messages,
          [convId]: [...existing, msg],
        },
        ...(updatedConv
          ? {
              conversations: {
                ...state.conversations,
                [convId]: updatedConv,
              },
            }
          : {}),
      };
    }),

  setMessages: (conversationId, messages) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [conversationId]: messages,
      },
    })),

  markRead: (conversationId) =>
    set((state) => {
      const conv = state.conversations[conversationId];
      if (!conv || conv.unreadCount === 0) return state;
      return {
        conversations: {
          ...state.conversations,
          [conversationId]: { ...conv, unreadCount: 0 },
        },
      };
    }),

  updateAgentStatus: (role, status, currentTask) =>
    set((state) => {
      const existing = state.agents[role];
      if (!existing) return state;
      return {
        agents: {
          ...state.agents,
          [role]: {
            ...existing,
            status,
            currentTask: currentTask ?? existing.currentTask,
            lastActive: new Date().toISOString(),
          },
        },
      };
    }),

  addConversation: (conversation) =>
    set((state) => ({
      conversations: {
        ...state.conversations,
        [conversation.id]: conversation,
      },
    })),

  setConversations: (conversations) =>
    set({
      conversations: Object.fromEntries(
        conversations.map((c) => [c.id, c])
      ),
    }),

  setAgents: (agents) =>
    set({
      agents: Object.fromEntries(
        agents.map((a) => [a.role, a])
      ) as Record<AgentRole, Agent>,
    }),
}));
