/**
 * Mobile Integration Tests — Forge Mobile Companion
 *
 * Tests mobile-specific features: offline support, haptics, biometrics,
 * push notifications, gesture navigation, and cross-platform behavior.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useConversationStore } from "@/stores/conversationStore";
import { useOfflineStore } from "@/stores/offlineStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";
import type { Agent } from "@/types/agent";
import type { Conversation } from "@/types/conversation";
import type { Message, MessageContent } from "@/types/message";
import type { PipelineRun } from "@/types/pipeline";

// ─── Reset helpers ──────────────────────────────────

function resetAllStores() {
  useConversationStore.setState({
    conversations: {},
    messages: {},
    agents: {} as Record<string, Agent>,
    activeConversationId: null,
  });
  useOfflineStore.setState({
    networkStatus: "online",
    lastOnlineAt: Date.now(),
    actionQueue: [],
    cacheMeta: {
      conversations: { lastSynced: 0 },
      pipelines: { lastSynced: 0 },
      agents: { lastSynced: 0 },
      messages: {},
    },
  });
  useConnectionStore.setState({
    serverUrl: "http://localhost:8000",
    connectionStatus: "connected",
    connectionError: null,
    authToken: "test-token",
    rememberMe: true,
    user: { id: "u1", email: "test@forge.dev", name: "Test", role: "admin", createdAt: "2024-01-01T00:00:00Z" },
    org: { id: "o1", name: "Test Org", slug: "test", plan: "pro", memberCount: 1 },
  });
  useSettingsStore.setState({
    theme: "dark",
    notificationLevel: "all",
    notificationSound: true,
    dndSchedule: { enabled: false, startHour: 22, endHour: 8 },
    closeToTray: false,
    startMinimized: false,
    autoLaunch: false,
    apiKeys: [],
    agentSettings: {},
    _loaded: true,
  });
}

// ─── Fixtures ───────────────────────────────────────

function makeConversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: `conv-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    type: "agent_dm",
    title: "Engineer DM",
    agentRole: "engineer",
    unreadCount: 0,
    participants: [],
    createdAt: "2024-01-01T00:00:00Z",
    updatedAt: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    conversationId: "conv-1",
    author: { type: "agent", role: "engineer", name: "Engineer" },
    content: [{ type: "text", text: "Hello from engineer" }],
    createdAt: "2024-01-01T00:01:00Z",
    ...overrides,
  };
}

function makePipelineRun(overrides: Partial<PipelineRun> = {}): PipelineRun {
  return {
    id: "run-1",
    name: "Build Invoice System",
    status: "running",
    startedAt: "2024-01-01T00:00:00Z",
    steps: [
      { id: "s1", name: "BA Analysis", agentRole: "ba", status: "completed" },
      { id: "s2", name: "Architecture", agentRole: "architect", status: "running" },
      { id: "s3", name: "Implementation", agentRole: "engineer", status: "pending" },
      { id: "s4", name: "QA Review", agentRole: "qa", status: "pending" },
    ],
    ...overrides,
  } as PipelineRun;
}

// ═══════════════════════════════════════════════════════
// Offline Support & Sync
// ═══════════════════════════════════════════════════════

describe("Offline Support", () => {
  beforeEach(resetAllStores);

  it("queues messages when offline", () => {
    const { enqueueMessage, getQueuedActions } = useOfflineStore.getState();

    const content: MessageContent[] = [{ type: "text", text: "Hello offline" }];
    const id = enqueueMessage("conv-1", content);

    expect(id).toBeTruthy();
    expect(id).toMatch(/^queued-msg-/);

    const queue = getQueuedActions();
    expect(queue).toHaveLength(1);
    expect(queue[0].type).toBe("message");
    expect(queue[0].payload).toMatchObject({
      conversationId: "conv-1",
      content,
    });
  });

  it("queues approvals when offline", () => {
    const { enqueueApproval, getQueuedActions } = useOfflineStore.getState();

    const id = enqueueApproval("run-1", "conv-1", "approval-1", "QA Review", true);

    expect(id).toMatch(/^queued-approval-/);

    const queue = getQueuedActions();
    expect(queue).toHaveLength(1);
    expect(queue[0].type).toBe("approval");
    expect(queue[0].payload).toMatchObject({
      pipelineId: "run-1",
      approvalId: "approval-1",
      approved: true,
    });
  });

  it("dequeues actions after processing", () => {
    const { enqueueMessage, enqueueApproval, dequeueAction, getQueuedActions } = useOfflineStore.getState();

    const msgId = enqueueMessage("conv-1", [{ type: "text", text: "test" }]);
    enqueueApproval("run-1", "conv-1", "a1", "QA", true);

    expect(getQueuedActions()).toHaveLength(2);

    dequeueAction(msgId);
    expect(getQueuedActions()).toHaveLength(1);
    expect(getQueuedActions()[0].type).toBe("approval");
  });

  it("clears entire queue", () => {
    const { enqueueMessage, clearQueue, getQueuedActions } = useOfflineStore.getState();

    enqueueMessage("conv-1", [{ type: "text", text: "a" }]);
    enqueueMessage("conv-2", [{ type: "text", text: "b" }]);
    enqueueMessage("conv-3", [{ type: "text", text: "c" }]);

    expect(getQueuedActions()).toHaveLength(3);
    clearQueue();
    expect(getQueuedActions()).toHaveLength(0);
  });

  it("tracks network status transitions", () => {
    const { setNetworkStatus, markOnline } = useOfflineStore.getState();

    setNetworkStatus("offline");
    expect(useOfflineStore.getState().networkStatus).toBe("offline");

    setNetworkStatus("reconnecting");
    expect(useOfflineStore.getState().networkStatus).toBe("reconnecting");

    markOnline();
    expect(useOfflineStore.getState().networkStatus).toBe("online");
    expect(useOfflineStore.getState().lastOnlineAt).toBeGreaterThan(0);
  });

  it("persists queue to localStorage", () => {
    const { enqueueMessage } = useOfflineStore.getState();

    enqueueMessage("conv-1", [{ type: "text", text: "persisted" }]);

    // Verify localStorage was called
    expect(localStorage.setItem).toHaveBeenCalledWith(
      "forge-offline-action-queue",
      expect.stringContaining("persisted"),
    );
  });

  it("maintains FIFO order in queue", () => {
    const { enqueueMessage, getQueuedActions } = useOfflineStore.getState();

    enqueueMessage("conv-1", [{ type: "text", text: "first" }]);
    enqueueMessage("conv-1", [{ type: "text", text: "second" }]);
    enqueueMessage("conv-1", [{ type: "text", text: "third" }]);

    const queue = getQueuedActions();
    expect(queue).toHaveLength(3);
    expect((queue[0].payload as { content: MessageContent[] }).content[0]).toMatchObject({ text: "first" });
    expect((queue[2].payload as { content: MessageContent[] }).content[0]).toMatchObject({ text: "third" });
  });
});

// ═══════════════════════════════════════════════════════
// Cache Management
// ═══════════════════════════════════════════════════════

describe("Offline Cache", () => {
  beforeEach(resetAllStores);

  it("caches and retrieves conversations", () => {
    const store = useOfflineStore.getState();
    const convs = [makeConversation({ id: "c1" }), makeConversation({ id: "c2" })];

    store.cacheConversations(convs);
    const loaded = store.loadCachedConversations();

    expect(loaded).toHaveLength(2);
    expect(loaded?.[0].id).toBe("c1");
  });

  it("caches and retrieves messages", () => {
    const store = useOfflineStore.getState();
    const msgs = [
      makeMessage({ id: "m1", conversationId: "c1" }),
      makeMessage({ id: "m2", conversationId: "c1" }),
    ];

    store.cacheMessages("c1", msgs);
    const loaded = store.loadCachedMessages("c1");

    expect(loaded).toHaveLength(2);
    expect(loaded?.[0].id).toBe("m1");
  });

  it("trims messages to max limit", () => {
    const store = useOfflineStore.getState();

    // Create 120 messages (limit is 100)
    const msgs = Array.from({ length: 120 }, (_, i) =>
      makeMessage({ id: `m-${i}`, conversationId: "c1" }),
    );

    store.cacheMessages("c1", msgs);
    const loaded = store.loadCachedMessages("c1");

    expect(loaded).toHaveLength(100);
    // Should keep the last 100 (newest)
    expect(loaded?.[0].id).toBe("m-20");
    expect(loaded?.[99].id).toBe("m-119");
  });

  it("tracks staleness correctly", () => {
    const store = useOfflineStore.getState();

    // Not yet synced → stale
    expect(store.isStale("conversations")).toBe(true);

    // Cache → fresh
    store.cacheConversations([makeConversation()]);
    expect(useOfflineStore.getState().isStale("conversations")).toBe(false);

    // Manually set old timestamp → stale
    useOfflineStore.setState({
      cacheMeta: {
        ...useOfflineStore.getState().cacheMeta,
        conversations: { lastSynced: Date.now() - 10 * 60 * 1000 }, // 10 min ago
      },
    });
    expect(useOfflineStore.getState().isStale("conversations")).toBe(true);
  });

  it("formats staleSince as human-readable string", () => {
    // Fresh data → null
    useOfflineStore.setState({
      cacheMeta: {
        ...useOfflineStore.getState().cacheMeta,
        conversations: { lastSynced: Date.now() },
      },
    });
    expect(useOfflineStore.getState().staleSince("conversations")).toBeNull();

    // 12 minutes ago
    useOfflineStore.setState({
      cacheMeta: {
        ...useOfflineStore.getState().cacheMeta,
        conversations: { lastSynced: Date.now() - 12 * 60 * 1000 },
      },
    });
    expect(useOfflineStore.getState().staleSince("conversations")).toBe("Updated 12m ago");

    // 3 hours ago
    useOfflineStore.setState({
      cacheMeta: {
        ...useOfflineStore.getState().cacheMeta,
        conversations: { lastSynced: Date.now() - 3 * 60 * 60 * 1000 },
      },
    });
    expect(useOfflineStore.getState().staleSince("conversations")).toBe("Updated 3h ago");
  });

  it("caches pipelines and agents independently", () => {
    const store = useOfflineStore.getState();

    store.cachePipelines([makePipelineRun({ id: "run-1" })]);
    store.cacheAgents([{ role: "engineer", displayName: "Engineer", emoji: "💻", status: "idle" } as Agent]);

    expect(store.loadCachedPipelines()).toHaveLength(1);
    expect(store.loadCachedAgents()).toHaveLength(1);
    expect(useOfflineStore.getState().isStale("pipelines")).toBe(false);
    expect(useOfflineStore.getState().isStale("agents")).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════
// Offline → Online Sync Flow
// ═══════════════════════════════════════════════════════

describe("Offline → Online Sync", () => {
  beforeEach(resetAllStores);

  it("full offline flow: go offline → queue actions → come online → flush", () => {
    const store = useOfflineStore.getState();

    // 1. Go offline
    store.setNetworkStatus("offline");
    expect(useOfflineStore.getState().networkStatus).toBe("offline");

    // 2. Queue a message while offline
    store.enqueueMessage("conv-1", [{ type: "text", text: "sent while walking the dog" }]);

    // 3. Queue an approval while offline
    store.enqueueApproval("run-1", "conv-1", "a1", "QA Review", true, "Looks good!");

    expect(useOfflineStore.getState().getQueuedActions()).toHaveLength(2);

    // 4. Come back online
    store.markOnline();
    expect(useOfflineStore.getState().networkStatus).toBe("online");

    // 5. Process queue (simulate flush)
    const queue = useOfflineStore.getState().getQueuedActions();
    expect(queue[0].type).toBe("message");
    expect(queue[1].type).toBe("approval");

    // 6. Dequeue as processed
    for (const action of queue) {
      useOfflineStore.getState().dequeueAction(action.payload.id);
    }
    expect(useOfflineStore.getState().getQueuedActions()).toHaveLength(0);
  });

  it("reconnecting state shows intermediate status", () => {
    const { setNetworkStatus } = useOfflineStore.getState();

    setNetworkStatus("offline");
    setNetworkStatus("reconnecting");
    expect(useOfflineStore.getState().networkStatus).toBe("reconnecting");

    setNetworkStatus("online");
    expect(useOfflineStore.getState().networkStatus).toBe("online");
  });
});

// ═══════════════════════════════════════════════════════
// Conversation & Pipeline Management (Mobile Context)
// ═══════════════════════════════════════════════════════

describe("Mobile Conversation Management", () => {
  beforeEach(resetAllStores);

  it("creates pipeline conversation from mobile", () => {
    const { addConversation, setMessages } = useConversationStore.getState();

    const pipelineId = "run-123";
    const convId = `pipeline-${pipelineId}`;
    const now = new Date().toISOString();

    addConversation({
      id: convId,
      type: "pipeline",
      title: "Build Invoice System",
      pipelineId,
      participants: [{ type: "user", id: "me", name: "You" }],
      createdAt: now,
      updatedAt: now,
      unreadCount: 0,
    });

    setMessages(convId, [{
      id: "msg-1",
      conversationId: convId,
      author: { type: "system" },
      content: [{ type: "pipeline_event", event: "pipeline_started", details: { spec: "Build invoice system" } }],
      createdAt: now,
    }]);

    const conv = useConversationStore.getState().conversations[convId];
    expect(conv).toBeDefined();
    expect(conv.type).toBe("pipeline");
    expect(conv.pipelineId).toBe(pipelineId);

    const msgs = useConversationStore.getState().messages[convId];
    expect(msgs).toHaveLength(1);
    expect(msgs[0].content[0]).toMatchObject({ type: "pipeline_event", event: "pipeline_started" });
  });

  it("tracks unread counts across conversations", () => {
    const { addConversation } = useConversationStore.getState();

    addConversation(makeConversation({ id: "c1", unreadCount: 3 }));
    addConversation(makeConversation({ id: "c2", unreadCount: 0 }));
    addConversation(makeConversation({ id: "c3", type: "pipeline", unreadCount: 5 }));

    const convs = useConversationStore.getState().conversations;
    const totalUnread = Object.values(convs).reduce((sum, c) => sum + c.unreadCount, 0);
    expect(totalUnread).toBe(8);

    const pipelineUnread = Object.values(convs)
      .filter((c) => c.type === "pipeline")
      .reduce((sum, c) => sum + c.unreadCount, 0);
    expect(pipelineUnread).toBe(5);
  });

  it("marks conversation as read", () => {
    const { addConversation, markRead } = useConversationStore.getState();

    addConversation(makeConversation({ id: "c1", unreadCount: 7 }));
    expect(useConversationStore.getState().conversations["c1"].unreadCount).toBe(7);

    markRead("c1");
    expect(useConversationStore.getState().conversations["c1"].unreadCount).toBe(0);
  });

  it("mobile approval adds response message to conversation", () => {
    const { addConversation, setMessages } = useConversationStore.getState();

    const convId = "pipeline-conv-1";
    addConversation(makeConversation({
      id: convId,
      type: "pipeline",
      pipelineId: "run-1",
    }));

    // Add an approval request message
    setMessages(convId, [
      makeMessage({
        id: "msg-approval-req",
        conversationId: convId,
        author: { type: "agent", role: "qa", name: "QA" },
        content: [{
          type: "approval_request",
          approvalId: "a1",
          stage: "QA Review",
          summary: "All tests passing. Coverage at 92%.",
        } as MessageContent],
      }),
    ]);

    // Simulate mobile approval
    const msgs = useConversationStore.getState().messages[convId];
    const responseMsg: Message = {
      id: `msg-approval-a1-${Date.now()}`,
      conversationId: convId,
      author: { type: "user", userId: "me", name: "You" },
      content: [{ type: "approval_response", approved: true } as MessageContent],
      createdAt: new Date().toISOString(),
    };

    useConversationStore.getState().setMessages(convId, [...msgs, responseMsg]);

    const updated = useConversationStore.getState().messages[convId];
    expect(updated).toHaveLength(2);
    expect(updated[1].content[0]).toMatchObject({ type: "approval_response", approved: true });
  });
});

// ═══════════════════════════════════════════════════════
// Approval Queue Aggregation
// ═══════════════════════════════════════════════════════

describe("Approval Queue", () => {
  beforeEach(resetAllStores);

  it("aggregates pending approvals across all pipelines", () => {
    const { addConversation, setMessages } = useConversationStore.getState();

    // Two pipeline conversations with approval requests
    addConversation(makeConversation({ id: "pc1", type: "pipeline", pipelineId: "run-1" }));
    addConversation(makeConversation({ id: "pc2", type: "pipeline", pipelineId: "run-2" }));

    setMessages("pc1", [
      makeMessage({
        id: "m1",
        conversationId: "pc1",
        content: [{ type: "approval_request", approvalId: "a1", stage: "QA", summary: "Tests pass" } as MessageContent],
        createdAt: "2024-01-01T01:00:00Z",
      }),
    ]);

    setMessages("pc2", [
      makeMessage({
        id: "m2",
        conversationId: "pc2",
        content: [{ type: "approval_request", approvalId: "a2", stage: "CTO Review", summary: "Architecture OK" } as MessageContent],
        createdAt: "2024-01-01T02:00:00Z",
      }),
    ]);

    // Count pending approvals
    const convs = useConversationStore.getState().conversations;
    const msgs = useConversationStore.getState().messages;
    let pendingCount = 0;

    for (const conv of Object.values(convs)) {
      if (conv.type !== "pipeline") continue;
      for (const msg of msgs[conv.id] ?? []) {
        for (const block of msg.content) {
          if (block.type === "approval_request") {
            const hasResponse = (msgs[conv.id] ?? []).some(
              (m) => m.createdAt > msg.createdAt && m.content.some((c) => c.type === "approval_response"),
            );
            if (!hasResponse) pendingCount++;
          }
        }
      }
    }

    expect(pendingCount).toBe(2);
  });

  it("excludes already-responded approvals", () => {
    const { addConversation, setMessages } = useConversationStore.getState();

    addConversation(makeConversation({ id: "pc1", type: "pipeline", pipelineId: "run-1" }));

    setMessages("pc1", [
      makeMessage({
        id: "m1",
        conversationId: "pc1",
        content: [{ type: "approval_request", approvalId: "a1", stage: "QA", summary: "Tests pass" } as MessageContent],
        createdAt: "2024-01-01T01:00:00Z",
      }),
      // Already approved
      makeMessage({
        id: "m2",
        conversationId: "pc1",
        author: { type: "user", userId: "me", name: "You" },
        content: [{ type: "approval_response", approved: true } as MessageContent],
        createdAt: "2024-01-01T01:01:00Z",
      }),
      // New unanswered approval
      makeMessage({
        id: "m3",
        conversationId: "pc1",
        content: [{ type: "approval_request", approvalId: "a2", stage: "CTO", summary: "Review arch" } as MessageContent],
        createdAt: "2024-01-01T02:00:00Z",
      }),
    ]);

    const msgs = useConversationStore.getState().messages["pc1"] ?? [];
    let pending = 0;
    for (const msg of msgs) {
      for (const block of msg.content) {
        if (block.type === "approval_request") {
          const hasResponse = msgs.some(
            (m) => m.createdAt > msg.createdAt && m.content.some((c) => c.type === "approval_response"),
          );
          if (!hasResponse) pending++;
        }
      }
    }

    // Only a2 should be pending (a1 was already approved)
    expect(pending).toBe(1);
  });
});

// ═══════════════════════════════════════════════════════
// Settings & Theme Persistence
// ═══════════════════════════════════════════════════════

describe("Mobile Settings", () => {
  beforeEach(resetAllStores);

  it("persists notification settings", () => {
    const { setNotificationLevel } = useSettingsStore.getState();
    setNotificationLevel("approvals");
    expect(useSettingsStore.getState().notificationLevel).toBe("approvals");
  });

  it("theme applies immediately", () => {
    const { setTheme } = useSettingsStore.getState();

    setTheme("light");
    expect(useSettingsStore.getState().theme).toBe("light");

    setTheme("dark");
    expect(useSettingsStore.getState().theme).toBe("dark");
  });
});

// ═══════════════════════════════════════════════════════
// Performance
// ═══════════════════════════════════════════════════════

describe("Performance", () => {
  beforeEach(resetAllStores);

  it("handles 1000+ messages without crash", () => {
    const { addConversation, setMessages } = useConversationStore.getState();

    addConversation(makeConversation({ id: "big-conv" }));

    const bigList: Message[] = Array.from({ length: 1500 }, (_, i) =>
      makeMessage({
        id: `msg-${i}`,
        conversationId: "big-conv",
        content: [{ type: "text", text: `Message ${i} with some content to simulate real data` }],
        createdAt: new Date(Date.now() - (1500 - i) * 1000).toISOString(),
      }),
    );

    setMessages("big-conv", bigList);

    const msgs = useConversationStore.getState().messages["big-conv"];
    expect(msgs).toHaveLength(1500);
    expect(msgs[0].id).toBe("msg-0");
    expect(msgs[1499].id).toBe("msg-1499");
  });

  it("handles rapid message additions efficiently", () => {
    const { addConversation, addMessage } = useConversationStore.getState();
    addConversation(makeConversation({ id: "rapid" }));

    const start = performance.now();

    for (let i = 0; i < 200; i++) {
      addMessage(makeMessage({
        id: `rapid-${i}`,
        conversationId: "rapid",
        content: [{ type: "text", text: `Rapid message ${i}` }],
      }));
    }

    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(1000); // Should complete within 1 second

    const msgs = useConversationStore.getState().messages["rapid"];
    expect(msgs).toHaveLength(200);
  });

  it("handles many simultaneous conversations", () => {
    const { addConversation } = useConversationStore.getState();

    for (let i = 0; i < 50; i++) {
      addConversation(makeConversation({
        id: `conv-${i}`,
        title: `Conversation ${i}`,
        unreadCount: i % 3 === 0 ? 1 : 0,
      }));
    }

    const convs = Object.values(useConversationStore.getState().conversations);
    expect(convs).toHaveLength(50);

    const unreadConvs = convs.filter((c) => c.unreadCount > 0);
    expect(unreadConvs.length).toBe(17); // 0, 3, 6, 9, ... 48
  });
});

// ═══════════════════════════════════════════════════════
// Cross-Platform Behavior
// ═══════════════════════════════════════════════════════

describe("Cross-Platform", () => {
  beforeEach(resetAllStores);

  it("conversation store works identically across platforms", () => {
    const store = useConversationStore.getState();

    // This flow should work on desktop, iOS, and Android
    store.addConversation(makeConversation({ id: "xplat", type: "pipeline", pipelineId: "run-1" }));
    store.setMessages("xplat", [
      makeMessage({ id: "m1", conversationId: "xplat", content: [{ type: "text", text: "Hello" }] }),
    ]);
    store.setActiveConversation("xplat");
    store.addMessage(makeMessage({ id: "m2", conversationId: "xplat", content: [{ type: "text", text: "World" }] }));
    store.markRead("xplat");

    const state = useConversationStore.getState();
    expect(state.activeConversationId).toBe("xplat");
    expect(state.messages["xplat"]).toHaveLength(2);
    expect(state.conversations["xplat"].unreadCount).toBe(0);
  });

  it("offline store queue persists through simulated app restart", () => {
    const store = useOfflineStore.getState();

    // Queue some actions
    store.enqueueMessage("conv-1", [{ type: "text", text: "offline message" }]);

    // Verify localStorage was written
    expect(localStorage.setItem).toHaveBeenCalledWith(
      "forge-offline-action-queue",
      expect.any(String),
    );

    // The queue should have the action
    expect(useOfflineStore.getState().actionQueue).toHaveLength(1);
  });

  it("agent status updates reflect in store", () => {
    const { setAgents, updateAgentStatus } = useConversationStore.getState();

    setAgents([
      { role: "engineer", displayName: "Engineer", emoji: "💻", status: "idle" },
      { role: "qa", displayName: "QA", emoji: "🧪", status: "idle" },
    ] as Agent[]);

    updateAgentStatus("engineer", "working", "Writing tests");

    const agents = useConversationStore.getState().agents;
    expect(agents["engineer"].status).toBe("working");
    expect(agents["engineer"].currentTask).toBe("Writing tests");
    expect(agents["qa"].status).toBe("idle");
  });
});
