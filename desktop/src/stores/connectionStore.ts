import { create } from "zustand";

// ─── Types ───────────────────────────────────────────

export type ConnectionStatus =
  | "unconfigured"
  | "connecting"
  | "connected"
  | "authenticated"
  | "disconnected"
  | "error";

export interface ForgeUser {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string;
  role: "admin" | "member" | "viewer";
  createdAt: string;
}

export interface ForgeOrg {
  id: string;
  name: string;
  slug: string;
  plan: "free" | "pro" | "enterprise";
  memberCount: number;
}

interface ConnectionState {
  // Connection
  serverUrl: string;
  connectionStatus: ConnectionStatus;
  connectionError: string | null;

  // Auth
  authToken: string | null;
  rememberMe: boolean;
  user: ForgeUser | null;
  org: ForgeOrg | null;

  // Actions
  setServerUrl: (url: string) => void;
  connect: () => Promise<boolean>;
  login: (email: string, password: string, remember: boolean) => Promise<void>;
  logout: () => void;
  restoreSession: () => Promise<void>;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setError: (error: string | null) => void;
}

// ─── Persistence helpers ─────────────────────────────

const STORAGE_KEY = "forge-connection";

interface PersistedConnection {
  serverUrl: string;
  authToken: string | null;
  rememberMe: boolean;
}

function loadPersisted(): Partial<PersistedConnection> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return {};
}

function savePersisted(data: PersistedConnection) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch { /* ignore */ }
}

// ─── Store ───────────────────────────────────────────

const persisted = loadPersisted();

export const useConnectionStore = create<ConnectionState>((set, get) => ({
  serverUrl: persisted.serverUrl ?? "",
  connectionStatus: persisted.serverUrl ? "disconnected" : "unconfigured",
  connectionError: null,
  authToken: persisted.rememberMe ? (persisted.authToken ?? null) : null,
  rememberMe: persisted.rememberMe ?? false,
  user: null,
  org: null,

  setServerUrl: (url) => {
    set({ serverUrl: url, connectionError: null });
    const state = get();
    savePersisted({
      serverUrl: url,
      authToken: state.authToken,
      rememberMe: state.rememberMe,
    });
  },

  connect: async () => {
    const { serverUrl } = get();
    if (!serverUrl) {
      set({ connectionError: "Server URL is required" });
      return false;
    }

    set({ connectionStatus: "connecting", connectionError: null });

    try {
      // Test connection by hitting the server health endpoint
      const res = await fetch(`${serverUrl}/api/health`, {
        signal: AbortSignal.timeout(5000),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      set({ connectionStatus: "connected" });
      savePersisted({
        serverUrl,
        authToken: get().authToken,
        rememberMe: get().rememberMe,
      });
      return true;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Connection failed";
      set({
        connectionStatus: "error",
        connectionError: `Could not reach server: ${message}`,
      });
      return false;
    }
  },

  login: async (email, password, remember) => {
    const { serverUrl } = get();
    set({ connectionStatus: "connecting", connectionError: null, rememberMe: remember });

    try {
      const res = await fetch(`${serverUrl}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Login failed" }));
        throw new Error(body.detail || `Login failed (${res.status})`);
      }

      const data = await res.json() as {
        token: string;
        user: ForgeUser;
        org: ForgeOrg;
      };

      set({
        authToken: data.token,
        user: data.user,
        org: data.org,
        connectionStatus: "authenticated",
        connectionError: null,
      });

      savePersisted({
        serverUrl,
        authToken: remember ? data.token : null,
        rememberMe: remember,
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Authentication failed";
      set({
        connectionStatus: "error",
        connectionError: message,
      });
      throw err;
    }
  },

  logout: () => {
    set({
      authToken: null,
      user: null,
      org: null,
      connectionStatus: "connected",
      connectionError: null,
    });
    const { serverUrl } = get();
    savePersisted({ serverUrl, authToken: null, rememberMe: false });
  },

  restoreSession: async () => {
    const { serverUrl, authToken } = get();
    if (!serverUrl || !authToken) return;

    set({ connectionStatus: "connecting" });

    try {
      const res = await fetch(`${serverUrl}/api/auth/me`, {
        headers: { Authorization: `Bearer ${authToken}` },
        signal: AbortSignal.timeout(5000),
      });

      if (!res.ok) {
        // Token expired or invalid
        set({ authToken: null, connectionStatus: "connected" });
        savePersisted({ serverUrl, authToken: null, rememberMe: false });
        return;
      }

      const data = await res.json() as { user: ForgeUser; org: ForgeOrg };
      set({
        user: data.user,
        org: data.org,
        connectionStatus: "authenticated",
      });
    } catch {
      // Server unreachable — stay disconnected but keep token for retry
      set({ connectionStatus: "disconnected" });
    }
  },

  setConnectionStatus: (status) => set({ connectionStatus: status }),
  setError: (error) => set({ connectionError: error }),
}));
