import { create } from "zustand";
import type {
  MCPConnection,
  ServicePreset,
  SetupGuide,
  TestConnectionResult,
  ToolWithPermission,
  AutomationConfig,
  ConnectionToolCall,
  OAuthStartResult,
} from "@/types/connection";
import { useConnectionStore } from "./connectionStore";

// ─── Helpers ─────────────────────────────────────────

function getAuthHeaders(): Record<string, string> {
  const { authToken } = useConnectionStore.getState();
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${authToken ?? ""}`,
  };
}

function getBaseUrl(): string {
  return useConnectionStore.getState().serverUrl ?? "";
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    ...opts,
    headers: { ...getAuthHeaders(), ...opts?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: `Request failed (${res.status})` }));
    throw new Error(body.detail ?? `Request failed (${res.status})`);
  }
  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

// ─── Store ───────────────────────────────────────────

interface MCPConnectionStore {
  // State
  connections: MCPConnection[];
  presets: ServicePreset[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchConnections: () => Promise<void>;
  fetchPresets: () => Promise<void>;
  fetchAll: () => Promise<void>;
  getConnection: (id: string) => Promise<MCPConnection>;
  createConnection: (data: {
    service: string;
    display_name: string;
    transport?: string;
    server_url?: string;
    credentials?: string;
    default_permission?: string;
    agent_permissions?: Record<string, string>;
  }) => Promise<MCPConnection>;
  deleteConnection: (id: string) => Promise<void>;
  testConnection: (id: string) => Promise<TestConnectionResult>;
  getConnectionTools: (id: string, agentRole?: string) => Promise<ToolWithPermission[]>;
  getSetupGuide: (service: string) => Promise<SetupGuide>;
  updatePermissions: (id: string, data: {
    default_permission?: string;
    agent_permissions?: Record<string, string>;
    tool_permissions?: Array<{ tool_name: string; allowed: boolean; allowed_agents?: string[] }>;
  }) => Promise<MCPConnection>;
  updateAutomation: (id: string, config: Partial<AutomationConfig>) => Promise<MCPConnection>;
  startOAuth: (service: string, data?: { connection_id?: string; display_name?: string }) => Promise<OAuthStartResult>;
  getPipelineActivity: (pipelineId: string) => Promise<ConnectionToolCall[]>;
  clearError: () => void;
}

export const useMCPConnectionStore = create<MCPConnectionStore>((set) => ({
  connections: [],
  presets: [],
  loading: false,
  error: null,

  fetchConnections: async () => {
    try {
      const connections = await apiFetch<MCPConnection[]>("/api/connections");
      set({ connections });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to load connections" });
    }
  },

  fetchPresets: async () => {
    try {
      const presets = await apiFetch<ServicePreset[]>("/api/connections/presets");
      set({ presets });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to load presets" });
    }
  },

  fetchAll: async () => {
    const base = getBaseUrl();
    const { authToken } = useConnectionStore.getState();
    if (!base || !authToken) return;
    set({ loading: true, error: null });
    try {
      const [connections, presets] = await Promise.all([
        apiFetch<MCPConnection[]>("/api/connections"),
        apiFetch<ServicePreset[]>("/api/connections/presets"),
      ]);
      set({ connections, presets });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to load connections" });
    } finally {
      set({ loading: false });
    }
  },

  getConnection: (id) => apiFetch<MCPConnection>(`/api/connections/${id}`),

  createConnection: async (data) => {
    const conn = await apiFetch<MCPConnection>("/api/connections", {
      method: "POST",
      body: JSON.stringify(data),
    });
    // Add to local cache
    set((s) => ({ connections: [...s.connections, conn] }));
    return conn;
  },

  deleteConnection: async (id) => {
    await apiFetch<void>(`/api/connections/${id}`, { method: "DELETE" });
    set((s) => ({ connections: s.connections.filter((c) => c.id !== id) }));
  },

  testConnection: (id) =>
    apiFetch<TestConnectionResult>(`/api/connections/${id}/test`, { method: "POST" }),

  getConnectionTools: (id, agentRole) => {
    const params = agentRole ? `?agent_role=${encodeURIComponent(agentRole)}` : "";
    return apiFetch<ToolWithPermission[]>(`/api/connections/${id}/tools${params}`);
  },

  getSetupGuide: (service) => apiFetch<SetupGuide>(`/api/connections/setup/${service}`),

  updatePermissions: async (id, data) => {
    const conn = await apiFetch<MCPConnection>(`/api/connections/${id}/permissions`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
    set((s) => ({ connections: s.connections.map((c) => (c.id === id ? conn : c)) }));
    return conn;
  },

  updateAutomation: async (id, config) => {
    const conn = await apiFetch<MCPConnection>(`/api/connections/${id}/automation`, {
      method: "PUT",
      body: JSON.stringify({ automation_config: config }),
    });
    set((s) => ({ connections: s.connections.map((c) => (c.id === id ? conn : c)) }));
    return conn;
  },

  startOAuth: (service, data) =>
    apiFetch<OAuthStartResult>(`/api/connections/oauth/start/${service}`, {
      method: "POST",
      body: JSON.stringify(data ?? {}),
    }),

  getPipelineActivity: (pipelineId) =>
    apiFetch<ConnectionToolCall[]>(`/api/connections/activity/${pipelineId}`),

  clearError: () => set({ error: null }),
}));
