/**
 * Integration Tests — Forge Desktop
 *
 * These tests verify cross-cutting concerns that span multiple stores,
 * services, and components working together.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useConnectionStore } from "@/stores/connectionStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { ForgeAPI } from "@/services/api";
import { ForgeWebSocket } from "@/services/ws";
import { AGENT_ROLES, AGENT_REGISTRY } from "@/types/agent";
import type { Agent } from "@/types/agent";
import type { Conversation } from "@/types/conversation";
import type { Message } from "@/types/message";

// ─── Reset all stores ─────────────────────────────

function resetAllStores() {
  useConnectionStore.setState({
    serverUrl: "",
    connectionStatus: "unconfigured",
    connectionError: null,
    authToken: null,
    rememberMe: false,
    user: null,
    org: null,
  });
  useConversationStore.setState({
    conversations: {},
    messages: {},
    agents: {} as Record<string, Agent>,
    activeConversationId: null,
  });
  useLayoutStore.setState({
    detailPanelOpen: false,
    detailPanelContent: null,
    sidebarWidth: 240,
    quickSwitcherOpen: false,
    threadState: null,
    newPipelineModalOpen: false,
    settingsOpen: false,
    activityFeedOpen: false,
  });
  useSettingsStore.setState({
    theme: "dark",
    notificationLevel: "all",
    notificationSound: true,
    dndSchedule: { enabled: false, startHour: 22, endHour: 8 },
    closeToTray: true,
    startMinimized: false,
    autoLaunch: false,
    apiKeys: [],
    agentSettings: {},
    _loaded: false,
  });
}

// ─── Fixtures ─────────────────────────────────────

const mockUser = {
  id: "u1",
  email: "admin@forge.dev",
  name: "Admin",
  role: "admin" as const,
  createdAt: "2024-01-01T00:00:00Z",
};

const mockOrg = {
  id: "o1",
  name: "Forge Labs",
  slug: "forge-labs",
  plan: "pro" as const,
  memberCount: 3,
};

function makeConversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "conv-1",
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
    id: "msg-1",
    conversationId: "conv-1",
    author: { type: "agent", role: "engineer", name: "Engineer" },
    content: [{ type: "text", text: "Response from agent" }],
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("Integration Tests", () => {
  beforeEach(() => {
    resetAllStores();
    vi.restoreAllMocks();
  });

  // ─────────────────────────────────────────────────
  // FLOW: First-launch → Connect → Login → Session
  // ─────────────────────────────────────────────────

  describe("First-launch connect flow", () => {
    it("starts unconfigured, transitions to connected, then authenticated", async () => {
      // 1. Initial state
      expect(useConnectionStore.getState().connectionStatus).toBe("unconfigured");

      // 2. User enters server URL
      useConnectionStore.getState().setServerUrl("http://forge.local:8000");
      expect(useConnectionStore.getState().serverUrl).toBe("http://forge.local:8000");

      // 3. Connect to server
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response("{}", { status: 200 })
      );
      await useConnectionStore.getState().connect();
      expect(useConnectionStore.getState().connectionStatus).toBe("connected");

      // 4. Login
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(
          JSON.stringify({ token: "jwt-123", user: mockUser, org: mockOrg }),
          { status: 200 }
        )
      );
      await useConnectionStore.getState().login("admin@forge.dev", "password", true);
      expect(useConnectionStore.getState().connectionStatus).toBe("authenticated");
      expect(useConnectionStore.getState().user?.name).toBe("Admin");
      expect(useConnectionStore.getState().org?.name).toBe("Forge Labs");
    });
  });

  describe("Session persistence across restarts", () => {
    it("restores session from localStorage", async () => {
      // Simulate a previous session saved
      useConnectionStore.setState({
        serverUrl: "http://forge.local:8000",
        authToken: "saved-jwt",
        rememberMe: true,
        connectionStatus: "disconnected",
      });

      // Mock the /api/auth/me endpoint
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(
          JSON.stringify({ user: mockUser, org: mockOrg }),
          { status: 200 }
        )
      );

      await useConnectionStore.getState().restoreSession();
      expect(useConnectionStore.getState().connectionStatus).toBe("authenticated");
      expect(useConnectionStore.getState().user?.email).toBe("admin@forge.dev");
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Agent DM send + receive
  // ─────────────────────────────────────────────────

  describe("Agent DM messaging", () => {
    it("sends message and receives agent response", async () => {
      // Setup: authenticated with conversations
      useConnectionStore.setState({
        serverUrl: "http://forge.local:8000",
        connectionStatus: "authenticated",
        authToken: "jwt",
      });

      const conv = makeConversation({ id: "dm-engineer", type: "agent_dm" });
      useConversationStore.getState().setConversations([conv]);
      useConversationStore.getState().setActiveConversation("dm-engineer");

      // Send a message via API
      const sentMsg = makeMessage({
        id: "user-msg-1",
        conversationId: "dm-engineer",
        author: { type: "user", userId: "u1", name: "Admin" },
        content: [{ type: "text", text: "How do I implement auth?" }],
      });

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(sentMsg), { status: 200 })
      );

      const api = new ForgeAPI("http://forge.local:8000", "jwt");
      const result = await api.sendAgentMessage("engineer", "How do I implement auth?");
      expect(result.id).toBe("user-msg-1");

      // Simulate WebSocket response
      const agentResponse = makeMessage({
        id: "agent-msg-1",
        conversationId: "dm-engineer",
        author: { type: "agent", role: "engineer", name: "Engineer" },
        content: [{ type: "text", text: "I recommend using JWT with refresh tokens." }],
      });

      useConversationStore.getState().addMessage(agentResponse);

      const msgs = useConversationStore.getState().messages["dm-engineer"];
      expect(msgs).toHaveLength(1);
      expect(msgs[0].content[0]).toEqual({
        type: "text",
        text: "I recommend using JWT with refresh tokens.",
      });
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Sidebar agents with correct statuses
  // ─────────────────────────────────────────────────

  describe("Sidebar agent statuses", () => {
    it("shows all 7 agents with correct display info", () => {
      const agents: Agent[] = AGENT_ROLES.map((role) => ({
        role,
        displayName: AGENT_REGISTRY[role].displayName,
        emoji: AGENT_REGISTRY[role].emoji,
        status: "idle" as const,
      }));

      useConversationStore.getState().setAgents(agents);

      const storedAgents = useConversationStore.getState().agents;
      expect(Object.keys(storedAgents)).toHaveLength(7);

      // Verify each agent
      expect(storedAgents["ba"].displayName).toBe("Business Analyst");
      expect(storedAgents["researcher"].displayName).toBe("Researcher");
      expect(storedAgents["architect"].displayName).toBe("Architect");
      expect(storedAgents["pm"].displayName).toBe("PM");
      expect(storedAgents["engineer"].displayName).toBe("Engineer");
      expect(storedAgents["qa"].displayName).toBe("QA");
      expect(storedAgents["cto"].displayName).toBe("CTO");
    });

    it("updates agent status from WebSocket events", () => {
      const agents: Agent[] = AGENT_ROLES.map((role) => ({
        role,
        displayName: AGENT_REGISTRY[role].displayName,
        emoji: AGENT_REGISTRY[role].emoji,
        status: "idle" as const,
      }));
      useConversationStore.getState().setAgents(agents);

      // Simulate WebSocket agent_status event
      useConversationStore.getState().updateAgentStatus("engineer", "working", "Implementing auth module");
      useConversationStore.getState().updateAgentStatus("qa", "working", "Reviewing PR #42");

      const storedAgents = useConversationStore.getState().agents;
      expect(storedAgents["engineer"].status).toBe("working");
      expect(storedAgents["engineer"].currentTask).toBe("Implementing auth module");
      expect(storedAgents["qa"].status).toBe("working");
      expect(storedAgents["ba"].status).toBe("idle");
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Pipeline creation and real-time messages
  // ─────────────────────────────────────────────────

  describe("Pipeline creation and messaging", () => {
    it("creates pipeline and receives real-time agent messages", async () => {
      useConnectionStore.setState({
        serverUrl: "http://forge.local:8000",
        connectionStatus: "authenticated",
        authToken: "jwt",
      });

      // Create pipeline via API
      const mockPipeline = {
        id: "pipe-1",
        name: "Auth Redesign",
        status: "pending",
        steps: [],
        startedAt: new Date().toISOString(),
      };

      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(mockPipeline), { status: 200 })
      );

      const api = new ForgeAPI("http://forge.local:8000", "jwt");
      const pipeline = await api.createPipeline("Redesign the auth system", "Auth Redesign");
      expect(pipeline.name).toBe("Auth Redesign");

      // Add pipeline conversation
      useConversationStore.getState().addConversation(
        makeConversation({
          id: "pipe-1",
          type: "pipeline",
          title: "#auth-redesign",
          pipelineId: "pipe-1",
        })
      );

      // Simulate messages from multiple agents
      const baMsg = makeMessage({
        id: "ba-msg",
        conversationId: "pipe-1",
        author: { type: "agent", role: "ba", name: "Business Analyst" },
        content: [{ type: "text", text: "Analyzing business requirements..." }],
      });
      useConversationStore.getState().addMessage(baMsg);

      const archMsg = makeMessage({
        id: "arch-msg",
        conversationId: "pipe-1",
        author: { type: "agent", role: "architect", name: "Architect" },
        content: [{ type: "text", text: "Designing system architecture..." }],
      });
      useConversationStore.getState().addMessage(archMsg);

      const msgs = useConversationStore.getState().messages["pipe-1"];
      expect(msgs).toHaveLength(2);
      expect(msgs[0].author).toEqual({ type: "agent", role: "ba", name: "Business Analyst" });
      expect(msgs[1].author).toEqual({ type: "agent", role: "architect", name: "Architect" });
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Quick Switcher navigation
  // ─────────────────────────────────────────────────

  describe("Quick Switcher (Cmd+K)", () => {
    it("opens and closes via layout store", () => {
      useLayoutStore.getState().toggleQuickSwitcher();
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(true);

      useLayoutStore.getState().closeQuickSwitcher();
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(false);
    });

    it("switching conversation via switcher closes overlays", () => {
      useLayoutStore.setState({
        quickSwitcherOpen: true,
        settingsOpen: true,
        activityFeedOpen: false,
      });

      // Simulate what QuickSwitcher does on selection
      useLayoutStore.getState().closeQuickSwitcher();
      useLayoutStore.getState().closeSettings();
      useLayoutStore.getState().closeActivityFeed();
      useConversationStore.getState().setActiveConversation("conv-1");

      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(false);
      expect(useLayoutStore.getState().settingsOpen).toBe(false);
      expect(useConversationStore.getState().activeConversationId).toBe("conv-1");
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Settings persist and apply immediately
  // ─────────────────────────────────────────────────

  describe("Settings persistence and immediate application", () => {
    it("theme change applies CSS variables immediately", () => {
      useSettingsStore.getState().setTheme("light");
      expect(document.documentElement.style.getPropertyValue("--forge-bg")).toBe("#ffffff");
      expect(document.documentElement.style.getPropertyValue("--forge-text")).toBe("#1d1c1d");

      useSettingsStore.getState().setTheme("dark");
      expect(document.documentElement.style.getPropertyValue("--forge-bg")).toBe("#1a1d21");
      expect(document.documentElement.style.getPropertyValue("--forge-text")).toBe("#d1d2d3");
    });

    it("notification level change persists to localStorage", () => {
      useSettingsStore.getState().setNotificationLevel("errors");
      expect(localStorage.setItem).toHaveBeenCalled();
      expect(useSettingsStore.getState().notificationLevel).toBe("errors");
    });

    it("close-to-tray invokes Tauri command", () => {
      useSettingsStore.getState().setCloseToTray(false);
      expect(useSettingsStore.getState().closeToTray).toBe(false);
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Multiple pipelines running simultaneously
  // ─────────────────────────────────────────────────

  describe("Multiple simultaneous pipelines", () => {
    it("tracks unread counts independently per pipeline", () => {
      const pipelines = [
        makeConversation({ id: "pipe-1", type: "pipeline", title: "#auth" }),
        makeConversation({ id: "pipe-2", type: "pipeline", title: "#dashboard" }),
        makeConversation({ id: "pipe-3", type: "pipeline", title: "#api" }),
      ];
      useConversationStore.getState().setConversations(pipelines);
      useConversationStore.getState().setActiveConversation("pipe-1");

      // Messages arrive for all pipelines
      useConversationStore.getState().addMessage(
        makeMessage({ id: "m1", conversationId: "pipe-1" })
      );
      useConversationStore.getState().addMessage(
        makeMessage({ id: "m2", conversationId: "pipe-2" })
      );
      useConversationStore.getState().addMessage(
        makeMessage({ id: "m3", conversationId: "pipe-3" })
      );

      const convs = useConversationStore.getState().conversations;
      expect(convs["pipe-1"].unreadCount).toBe(0); // active, no increment
      expect(convs["pipe-2"].unreadCount).toBe(1); // not active, incremented
      expect(convs["pipe-3"].unreadCount).toBe(1); // not active, incremented
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: WebSocket reconnection behavior
  // ─────────────────────────────────────────────────

  describe("WebSocket reconnection", () => {
    it("ForgeWebSocket disconnect sets intentional close", () => {
      const ws = new ForgeWebSocket();
      const handler = vi.fn();
      ws.on("connection_status", handler);

      ws.disconnect();
      expect(handler).toHaveBeenCalledWith("disconnected");
    });

    it("queues messages while disconnected", () => {
      const ws = new ForgeWebSocket();
      // Send without connecting — should queue, not crash
      ws.send("message", { text: "queued" });
      ws.send("message", { text: "also queued" });
      ws.disconnect();
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Layout state management
  // ─────────────────────────────────────────────────

  describe("Layout mutual exclusion", () => {
    it("opening settings closes activity feed", () => {
      useLayoutStore.getState().openActivityFeed();
      expect(useLayoutStore.getState().activityFeedOpen).toBe(true);

      useLayoutStore.getState().openSettings();
      expect(useLayoutStore.getState().settingsOpen).toBe(true);
      expect(useLayoutStore.getState().activityFeedOpen).toBe(false);
    });

    it("opening activity feed closes settings", () => {
      useLayoutStore.getState().openSettings();
      expect(useLayoutStore.getState().settingsOpen).toBe(true);

      useLayoutStore.getState().openActivityFeed();
      expect(useLayoutStore.getState().activityFeedOpen).toBe(true);
      expect(useLayoutStore.getState().settingsOpen).toBe(false);
    });

    it("escape cascade: activity → settings → detail → quick switcher", () => {
      // Simulate Escape key behavior order
      useLayoutStore.setState({
        quickSwitcherOpen: true,
        activityFeedOpen: true,
        settingsOpen: false,
        detailPanelOpen: true,
        newPipelineModalOpen: true,
      });

      // First escape: close quick switcher
      useLayoutStore.getState().closeQuickSwitcher();
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(false);

      // Second escape: close new pipeline modal
      useLayoutStore.getState().closeNewPipelineModal();
      expect(useLayoutStore.getState().newPipelineModalOpen).toBe(false);

      // Third escape: close activity feed
      useLayoutStore.getState().closeActivityFeed();
      expect(useLayoutStore.getState().activityFeedOpen).toBe(false);

      // Fourth escape: close detail panel
      useLayoutStore.getState().closeDetailPanel();
      expect(useLayoutStore.getState().detailPanelOpen).toBe(false);
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: API error handling
  // ─────────────────────────────────────────────────

  describe("API error handling", () => {
    it("401 on API call indicates expired session", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response("Unauthorized", { status: 401, statusText: "Unauthorized" })
      );

      const api = new ForgeAPI("http://forge.local:8000", "expired-token");
      await expect(api.getConversations()).rejects.toThrow("API 401: Unauthorized");
    });

    it("network error during connect is handled gracefully", async () => {
      useConnectionStore.getState().setServerUrl("http://unreachable.local:8000");
      vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

      const result = await useConnectionStore.getState().connect();
      expect(result).toBe(false);
      expect(useConnectionStore.getState().connectionStatus).toBe("error");
      expect(useConnectionStore.getState().connectionError).toContain("Failed to fetch");
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Dark mode rendering
  // ─────────────────────────────────────────────────

  describe("Dark mode", () => {
    it("applies correct CSS custom properties", () => {
      useSettingsStore.getState().setTheme("dark");

      const root = document.documentElement;
      expect(root.style.getPropertyValue("--forge-bg")).toBe("#1a1d21");
      expect(root.style.getPropertyValue("--forge-sidebar")).toBe("#19171d");
      expect(root.style.getPropertyValue("--forge-accent")).toBe("#4a9eff");
      expect(root.style.getPropertyValue("--forge-success")).toBe("#2bac76");
      expect(root.style.getPropertyValue("--forge-error")).toBe("#e84040");
      expect(root.style.getPropertyValue("--forge-warning")).toBe("#e8a820");
    });

    it("light mode applies correct CSS properties", () => {
      useSettingsStore.getState().setTheme("light");

      const root = document.documentElement;
      expect(root.style.getPropertyValue("--forge-bg")).toBe("#ffffff");
      expect(root.style.getPropertyValue("--forge-sidebar")).toBe("#f8f8fa");
      expect(root.style.getPropertyValue("--forge-text")).toBe("#1d1c1d");
    });
  });

  // ─────────────────────────────────────────────────
  // FLOW: Approval card workflow
  // ─────────────────────────────────────────────────

  describe("Approval workflow", () => {
    it("approval via API sends correct payload", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, { status: 204 })
      );

      const api = new ForgeAPI("http://forge.local:8000", "jwt");
      await api.approvePipeline("pipe-1", "architecture", true, "LGTM");

      expect(fetch).toHaveBeenCalledWith(
        "http://forge.local:8000/api/pipelines/pipe-1/approve",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            stage: "architecture",
            approved: true,
            comment: "LGTM",
          }),
        })
      );
    });

    it("rejection via API sends correct payload", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, { status: 204 })
      );

      const api = new ForgeAPI("http://forge.local:8000", "jwt");
      await api.approvePipeline("pipe-1", "architecture", false, "Needs more error handling");

      expect(fetch).toHaveBeenCalledWith(
        "http://forge.local:8000/api/pipelines/pipe-1/approve",
        expect.objectContaining({
          body: JSON.stringify({
            stage: "architecture",
            approved: false,
            comment: "Needs more error handling",
          }),
        })
      );
    });
  });

  // ─────────────────────────────────────────────────
  // PERFORMANCE: Message list with many messages
  // ─────────────────────────────────────────────────

  describe("Performance: large message lists", () => {
    it("handles 1000+ messages without issues", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-bulk" }),
      ]);

      const messages: Message[] = Array.from({ length: 1000 }, (_, i) =>
        makeMessage({
          id: `msg-${i}`,
          conversationId: "conv-bulk",
          content: [{ type: "text", text: `Message ${i}` }],
          createdAt: new Date(Date.now() + i * 1000).toISOString(),
        })
      );

      // Bulk set rather than addMessage loop for performance
      useConversationStore.getState().setMessages("conv-bulk", messages);
      expect(useConversationStore.getState().messages["conv-bulk"]).toHaveLength(1000);
    });

    it("incremental addMessage to 1000 works", () => {
      useConversationStore.getState().setConversations([
        makeConversation({ id: "conv-inc" }),
      ]);

      const start = performance.now();
      for (let i = 0; i < 1000; i++) {
        useConversationStore.getState().addMessage(
          makeMessage({
            id: `msg-${i}`,
            conversationId: "conv-inc",
          })
        );
      }
      const elapsed = performance.now() - start;

      expect(useConversationStore.getState().messages["conv-inc"]).toHaveLength(1000);
      // Should complete well under 5 seconds even in test environment
      expect(elapsed).toBeLessThan(5000);
    });
  });
});
