import { create } from "zustand";
import type { Conversation } from "@/types/conversation";
import type { Message, MessageContent } from "@/types/message";
import type { PipelineRun } from "@/types/pipeline";
import type { Agent } from "@/types/agent";

// ─── Constants ──────────────────────────────────────

const STORAGE_PREFIX = "forge-offline-";
const MAX_MESSAGES_PER_CONVERSATION = 100;
const STALE_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes

// ─── Network status ─────────────────────────────────

export type NetworkStatus = "online" | "reconnecting" | "offline";

// ─── Queued action types ────────────────────────────

export interface QueuedMessage {
  id: string;
  conversationId: string;
  content: MessageContent[];
  queuedAt: number;
}

export interface QueuedApproval {
  id: string;
  pipelineId: string;
  conversationId: string;
  approvalId: string;
  stage: string;
  approved: boolean;
  comment?: string;
  queuedAt: number;
}

export type QueuedAction =
  | { type: "message"; payload: QueuedMessage }
  | { type: "approval"; payload: QueuedApproval };

// ─── Cache metadata ─────────────────────────────────

interface CacheMeta {
  lastSynced: number; // epoch ms
}

// ─── Store interface ────────────────────────────────

interface OfflineState {
  // Network status
  networkStatus: NetworkStatus;
  lastOnlineAt: number | null;

  // Outgoing action queue
  actionQueue: QueuedAction[];

  // Cache timestamps
  cacheMeta: {
    conversations: CacheMeta;
    pipelines: CacheMeta;
    agents: CacheMeta;
    messages: Record<string, CacheMeta>;
  };

  // Actions — network
  setNetworkStatus: (status: NetworkStatus) => void;
  markOnline: () => void;

  // Actions — queue
  enqueueMessage: (conversationId: string, content: MessageContent[]) => string;
  enqueueApproval: (
    pipelineId: string,
    conversationId: string,
    approvalId: string,
    stage: string,
    approved: boolean,
    comment?: string,
  ) => string;
  dequeueAction: (id: string) => void;
  getQueuedActions: () => QueuedAction[];
  clearQueue: () => void;

  // Actions — cache
  cacheConversations: (conversations: Conversation[]) => void;
  cacheMessages: (conversationId: string, messages: Message[]) => void;
  cachePipelines: (pipelines: PipelineRun[]) => void;
  cacheAgents: (agents: Agent[]) => void;

  loadCachedConversations: () => Conversation[] | null;
  loadCachedMessages: (conversationId: string) => Message[] | null;
  loadCachedPipelines: () => PipelineRun[] | null;
  loadCachedAgents: () => Agent[] | null;

  getLastSynced: (key: "conversations" | "pipelines" | "agents") => number | null;
  getMessageLastSynced: (conversationId: string) => number | null;
  isStale: (key: "conversations" | "pipelines" | "agents") => boolean;
  isMessageStale: (conversationId: string) => boolean;
  staleSince: (key: "conversations" | "pipelines" | "agents") => string | null;
}

// ─── Persistence helpers ────────────────────────────

function saveToStorage(key: string, data: unknown): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(data));
  } catch {
    // Storage full — evict oldest messages cache
    evictOldestCache();
    try {
      localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(data));
    } catch { /* give up */ }
  }
}

function loadFromStorage<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key);
    if (raw) return JSON.parse(raw) as T;
  } catch { /* corrupt data */ }
  return null;
}

function evictOldestCache(): void {
  // Find and remove the oldest messages-* entry
  const keys: Array<{ key: string; time: number }> = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k?.startsWith(STORAGE_PREFIX + "messages-")) {
      try {
        const meta = localStorage.getItem(k + "-meta");
        if (meta) keys.push({ key: k, time: JSON.parse(meta).lastSynced });
      } catch { /* ignore */ }
    }
  }
  keys.sort((a, b) => a.time - b.time);
  if (keys.length > 0) {
    localStorage.removeItem(keys[0].key);
    localStorage.removeItem(keys[0].key + "-meta");
  }
}

// ─── Load persisted queue ───────────────────────────

function loadPersistedQueue(): QueuedAction[] {
  return loadFromStorage<QueuedAction[]>("action-queue") ?? [];
}

function loadPersistedMeta(): OfflineState["cacheMeta"] {
  return loadFromStorage<OfflineState["cacheMeta"]>("cache-meta") ?? {
    conversations: { lastSynced: 0 },
    pipelines: { lastSynced: 0 },
    agents: { lastSynced: 0 },
    messages: {},
  };
}

// ─── Store ──────────────────────────────────────────

export const useOfflineStore = create<OfflineState>((set, get) => ({
  networkStatus: "online",
  lastOnlineAt: Date.now(),
  actionQueue: loadPersistedQueue(),
  cacheMeta: loadPersistedMeta(),

  // ── Network ──────────────────────────────────────

  setNetworkStatus: (status) => {
    set({ networkStatus: status });
    if (status === "online") {
      set({ lastOnlineAt: Date.now() });
    }
  },

  markOnline: () => {
    set({ networkStatus: "online", lastOnlineAt: Date.now() });
  },

  // ── Queue ────────────────────────────────────────

  enqueueMessage: (conversationId, content) => {
    const id = `queued-msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const action: QueuedAction = {
      type: "message",
      payload: {
        id,
        conversationId,
        content,
        queuedAt: Date.now(),
      },
    };
    set((state) => {
      const queue = [...state.actionQueue, action];
      saveToStorage("action-queue", queue);
      return { actionQueue: queue };
    });
    return id;
  },

  enqueueApproval: (pipelineId, conversationId, approvalId, stage, approved, comment) => {
    const id = `queued-approval-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const action: QueuedAction = {
      type: "approval",
      payload: {
        id,
        pipelineId,
        conversationId,
        approvalId,
        stage,
        approved,
        comment,
        queuedAt: Date.now(),
      },
    };
    set((state) => {
      const queue = [...state.actionQueue, action];
      saveToStorage("action-queue", queue);
      return { actionQueue: queue };
    });
    return id;
  },

  dequeueAction: (id) => {
    set((state) => {
      const queue = state.actionQueue.filter((a) => {
        if (a.type === "message") return a.payload.id !== id;
        return a.payload.id !== id;
      });
      saveToStorage("action-queue", queue);
      return { actionQueue: queue };
    });
  },

  getQueuedActions: () => get().actionQueue,

  clearQueue: () => {
    saveToStorage("action-queue", []);
    set({ actionQueue: [] });
  },

  // ── Cache: write ─────────────────────────────────

  cacheConversations: (conversations) => {
    saveToStorage("conversations", conversations);
    set((state) => {
      const meta = {
        ...state.cacheMeta,
        conversations: { lastSynced: Date.now() },
      };
      saveToStorage("cache-meta", meta);
      return { cacheMeta: meta };
    });
  },

  cacheMessages: (conversationId, messages) => {
    // Keep only the last N messages
    const trimmed = messages.slice(-MAX_MESSAGES_PER_CONVERSATION);
    saveToStorage(`messages-${conversationId}`, trimmed);
    set((state) => {
      const meta = {
        ...state.cacheMeta,
        messages: {
          ...state.cacheMeta.messages,
          [conversationId]: { lastSynced: Date.now() },
        },
      };
      saveToStorage("cache-meta", meta);
      return { cacheMeta: meta };
    });
  },

  cachePipelines: (pipelines) => {
    saveToStorage("pipelines", pipelines);
    set((state) => {
      const meta = {
        ...state.cacheMeta,
        pipelines: { lastSynced: Date.now() },
      };
      saveToStorage("cache-meta", meta);
      return { cacheMeta: meta };
    });
  },

  cacheAgents: (agents) => {
    saveToStorage("agents", agents);
    set((state) => {
      const meta = {
        ...state.cacheMeta,
        agents: { lastSynced: Date.now() },
      };
      saveToStorage("cache-meta", meta);
      return { cacheMeta: meta };
    });
  },

  // ── Cache: read ──────────────────────────────────

  loadCachedConversations: () => loadFromStorage<Conversation[]>("conversations"),
  loadCachedMessages: (conversationId) => loadFromStorage<Message[]>(`messages-${conversationId}`),
  loadCachedPipelines: () => loadFromStorage<PipelineRun[]>("pipelines"),
  loadCachedAgents: () => loadFromStorage<Agent[]>("agents"),

  // ── Cache: freshness ─────────────────────────────

  getLastSynced: (key) => {
    const ts = get().cacheMeta[key]?.lastSynced;
    return ts && ts > 0 ? ts : null;
  },

  getMessageLastSynced: (conversationId) => {
    const ts = get().cacheMeta.messages[conversationId]?.lastSynced;
    return ts && ts > 0 ? ts : null;
  },

  isStale: (key) => {
    const ts = get().cacheMeta[key]?.lastSynced;
    if (!ts || ts === 0) return true;
    return Date.now() - ts > STALE_THRESHOLD_MS;
  },

  isMessageStale: (conversationId) => {
    const ts = get().cacheMeta.messages[conversationId]?.lastSynced;
    if (!ts || ts === 0) return true;
    return Date.now() - ts > STALE_THRESHOLD_MS;
  },

  staleSince: (key) => {
    const ts = get().cacheMeta[key]?.lastSynced;
    if (!ts || ts === 0) return null;
    const diffMs = Date.now() - ts;
    if (diffMs < STALE_THRESHOLD_MS) return null;

    const minutes = Math.floor(diffMs / 60_000);
    if (minutes < 60) return `Updated ${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `Updated ${hours}h ago`;
    return `Updated ${Math.floor(hours / 24)}d ago`;
  },
}));
