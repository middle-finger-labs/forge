import { describe, it, expect, beforeEach } from "vitest";
import { useConversationStore } from "@/stores/conversationStore";
import type { Conversation } from "@/types/conversation";
import type { Message } from "@/types/message";
import type { Agent } from "@/types/agent";

// ─── Fixtures ─────────────────────────────────────

const makeConversation = (overrides: Partial<Conversation> = {}): Conversation => ({
  id: "conv-1",
  type: "agent_dm",
  title: "Engineer DM",
  agentRole: "engineer",
  unreadCount: 0,
  participants: [],
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-01-01T00:00:00Z",
  ...overrides,
});

const makeMessage = (overrides: Partial<Message> = {}): Message => ({
  id: "msg-1",
  conversationId: "conv-1",
  author: { type: "agent", role: "engineer", name: "Engineer" },
  content: [{ type: "text", text: "Hello" }],
  createdAt: "2024-01-01T00:01:00Z",
  ...overrides,
});

const makeAgent = (overrides: Partial<Agent> = {}): Agent => ({
  role: "engineer",
  displayName: "Engineer",
  emoji: "\u{1F4BB}",
  status: "idle",
  ...overrides,
});

function resetStore() {
  useConversationStore.setState({
    conversations: {},
    messages: {},
    agents: {} as Record<string, Agent>,
    activeConversationId: null,
  });
}

describe("conversationStore", () => {
  beforeEach(resetStore);

  // ─── Conversations ──────────────────────────────

  describe("conversations", () => {
    it("setConversations indexes by id", () => {
      const convs = [
        makeConversation({ id: "c1", title: "One" }),
        makeConversation({ id: "c2", title: "Two" }),
      ];
      useConversationStore.getState().setConversations(convs);
      const state = useConversationStore.getState();

      expect(Object.keys(state.conversations)).toHaveLength(2);
      expect(state.conversations["c1"].title).toBe("One");
      expect(state.conversations["c2"].title).toBe("Two");
    });

    it("addConversation appends a new conversation", () => {
      useConversationStore.getState().addConversation(
        makeConversation({ id: "new", title: "New Conv" })
      );
      expect(useConversationStore.getState().conversations["new"].title).toBe("New Conv");
    });
  });

  // ─── Active conversation ────────────────────────

  describe("setActiveConversation", () => {
    it("sets activeConversationId and marks read", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "c1", unreadCount: 5 }),
      ]);

      useConversationStore.getState().setActiveConversation("c1");
      const state = useConversationStore.getState();

      expect(state.activeConversationId).toBe("c1");
      expect(state.conversations["c1"].unreadCount).toBe(0);
    });

    it("can be set to null", () => {
      useConversationStore.getState().setActiveConversation(null);
      expect(useConversationStore.getState().activeConversationId).toBeNull();
    });
  });

  // ─── Messages ───────────────────────────────────

  describe("addMessage", () => {
    it("appends message to the correct conversation", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-1" }),
      ]);

      useConversationStore.getState().addMessage(makeMessage());
      const msgs = useConversationStore.getState().messages["conv-1"];

      expect(msgs).toHaveLength(1);
      expect(msgs[0].content[0]).toEqual({ type: "text", text: "Hello" });
    });

    it("updates lastMessage on the conversation", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-1" }),
      ]);

      const msg = makeMessage({ id: "msg-2", createdAt: "2024-01-01T00:05:00Z" });
      useConversationStore.getState().addMessage(msg);

      const conv = useConversationStore.getState().conversations["conv-1"];
      expect(conv.lastMessage?.id).toBe("msg-2");
      expect(conv.updatedAt).toBe("2024-01-01T00:05:00Z");
    });

    it("increments unreadCount when not active conversation", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-1", unreadCount: 0 }),
      ]);
      // Active is something else
      useConversationStore.getState().setActiveConversation(null);

      useConversationStore.getState().addMessage(makeMessage());
      expect(useConversationStore.getState().conversations["conv-1"].unreadCount).toBe(1);

      useConversationStore.getState().addMessage(makeMessage({ id: "msg-2" }));
      expect(useConversationStore.getState().conversations["conv-1"].unreadCount).toBe(2);
    });

    it("does NOT increment unreadCount for active conversation", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-1", unreadCount: 0 }),
      ]);
      useConversationStore.getState().setActiveConversation("conv-1");

      useConversationStore.getState().addMessage(makeMessage());
      expect(useConversationStore.getState().conversations["conv-1"].unreadCount).toBe(0);
    });

    it("handles messages for unknown conversations gracefully", () => {
      useConversationStore.getState().addMessage(
        makeMessage({ conversationId: "unknown" })
      );
      const msgs = useConversationStore.getState().messages["unknown"];
      expect(msgs).toHaveLength(1);
    });

    it("supports multiple messages building up a conversation", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-1" }),
      ]);

      for (let i = 0; i < 50; i++) {
        useConversationStore.getState().addMessage(
          makeMessage({ id: `msg-${i}`, conversationId: "conv-1" })
        );
      }

      expect(useConversationStore.getState().messages["conv-1"]).toHaveLength(50);
    });
  });

  describe("setMessages", () => {
    it("replaces all messages for a conversation", () => {
      const msgs = [makeMessage({ id: "a" }), makeMessage({ id: "b" })];
      useConversationStore.getState().setMessages("conv-1", msgs);

      expect(useConversationStore.getState().messages["conv-1"]).toHaveLength(2);
    });
  });

  // ─── Mark read ──────────────────────────────────

  describe("markRead", () => {
    it("resets unreadCount to 0", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "c1", unreadCount: 10 }),
      ]);

      useConversationStore.getState().markRead("c1");
      expect(useConversationStore.getState().conversations["c1"].unreadCount).toBe(0);
    });

    it("is a no-op for already-read conversations", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "c1", unreadCount: 0 }),
      ]);

      useConversationStore.getState().markRead("c1");
      expect(useConversationStore.getState().conversations["c1"].unreadCount).toBe(0);
    });
  });

  // ─── Agents ─────────────────────────────────────

  describe("agents", () => {
    it("setAgents indexes by role", () => {
      useConversationStore.getState().setAgents([
        makeAgent({ role: "engineer" }),
        makeAgent({ role: "qa", displayName: "QA" }),
      ]);

      const agents = useConversationStore.getState().agents;
      expect(agents["engineer"].displayName).toBe("Engineer");
      expect(agents["qa"].displayName).toBe("QA");
    });

    it("updateAgentStatus changes status and currentTask", () => {
      useConversationStore.getState().setAgents([makeAgent({ role: "engineer", status: "idle" })]);

      useConversationStore.getState().updateAgentStatus("engineer", "working", "Implementing auth");
      const agent = useConversationStore.getState().agents["engineer"];

      expect(agent.status).toBe("working");
      expect(agent.currentTask).toBe("Implementing auth");
      expect(agent.lastActive).toBeDefined();
    });

    it("updateAgentStatus preserves currentTask if not provided", () => {
      useConversationStore.getState().setAgents([
        makeAgent({ role: "engineer", status: "working", currentTask: "Old task" }),
      ]);

      useConversationStore.getState().updateAgentStatus("engineer", "idle");
      expect(useConversationStore.getState().agents["engineer"].currentTask).toBe("Old task");
    });

    it("updateAgentStatus is no-op for unknown roles", () => {
      const before = useConversationStore.getState();
      useConversationStore.getState().updateAgentStatus("engineer", "working");
      expect(useConversationStore.getState()).toBe(before);
    });
  });

  // ─── Multiple pipelines running simultaneously ──

  describe("multiple active pipelines", () => {
    it("tracks messages across multiple pipeline conversations", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "pipe-1", type: "pipeline", title: "Auth Redesign" }),
        makeConversation({ id: "pipe-2", type: "pipeline", title: "Dashboard v2" }),
        makeConversation({ id: "pipe-3", type: "pipeline", title: "API Rate Limiting" }),
      ]);

      // Simulate messages arriving from different pipelines
      useConversationStore.getState().addMessage(
        makeMessage({ id: "m1", conversationId: "pipe-1" })
      );
      useConversationStore.getState().addMessage(
        makeMessage({ id: "m2", conversationId: "pipe-2" })
      );
      useConversationStore.getState().addMessage(
        makeMessage({ id: "m3", conversationId: "pipe-3" })
      );

      expect(useConversationStore.getState().messages["pipe-1"]).toHaveLength(1);
      expect(useConversationStore.getState().messages["pipe-2"]).toHaveLength(1);
      expect(useConversationStore.getState().messages["pipe-3"]).toHaveLength(1);
    });
  });
});
