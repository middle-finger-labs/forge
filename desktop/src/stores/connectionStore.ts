import { create } from "zustand";
import { invoke } from "@tauri-apps/api/core";
import { saveSecureToken, getSecureToken, deleteSecureToken } from "@/services/secureStorage";

// ─── Tauri proxy helper ─────────────────────────────

interface ProxyResponse {
  status: number;
  body: string;
  headers: Record<string, string>;
}

async function tauriFetch(
  url: string,
  opts?: { method?: string; body?: string; token?: string }
): Promise<{ ok: boolean; status: number; headers: Record<string, string>; json: () => Promise<unknown> }> {
  const res = await invoke<ProxyResponse>("proxy_fetch", {
    url,
    method: opts?.method ?? "GET",
    body: opts?.body ?? null,
    authToken: opts?.token ?? null,
  });
  return {
    ok: res.status >= 200 && res.status < 300,
    status: res.status,
    headers: res.headers,
    json: async () => JSON.parse(res.body),
  };
}

/** Extract Better Auth session token from Set-Cookie header */
function extractSessionToken(headers: Record<string, string>): string | null {
  const cookies = headers["set-cookie"] ?? "";
  // Look for better-auth.session_token or __Secure-better-auth.session_token
  for (const part of cookies.split(";")) {
    const trimmed = part.trim();
    const match = trimmed.match(/(?:__Secure-)?better-auth\.session_token=(.+)/);
    if (match) return match[1];
  }
  return null;
}

// ─── Types ───────────────────────────────────────────

export type ConnectionStatus =
  | "unconfigured"
  | "connecting"
  | "connected"
  | "authenticated"
  | "disconnected"
  | "error"
  | "awaiting_magic_link";

export interface ServerInfo {
  name: string;
  version: string;
  server_url: string;
  auth_methods: string[];
  logo_url: string | null;
}

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

export interface MagicLinkStatusResponse {
  status: "pending" | "consumed" | "expired" | "not_found";
  token?: string;
}

interface ConnectionState {
  // Connection
  serverUrl: string;
  authUrl: string;
  serverInfo: ServerInfo | null;
  connectionStatus: ConnectionStatus;
  connectionError: string | null;

  // Auth
  authToken: string | null;
  rememberMe: boolean;
  user: ForgeUser | null;
  org: ForgeOrg | null;
  magicLinkEmail: string | null;

  // Discovery
  isDiscovering: boolean;

  // Resend cooldown
  cooldownRemaining: number;

  // Actions
  setServerUrl: (url: string) => void;
  connect: () => Promise<boolean>;
  login: (email: string, password: string, remember: boolean) => Promise<void>;
  requestMagicLink: (email: string) => Promise<void>;
  verifyMagicLink: (token: string, serverUrl?: string) => Promise<void>;
  discoverServer: (email: string) => Promise<string | null>;
  checkMagicLinkStatus: () => Promise<MagicLinkStatusResponse>;
  logout: () => void;
  restoreSession: () => Promise<void>;
  initializeAuth: () => Promise<void>;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setError: (error: string | null) => void;
  setCooldownRemaining: (seconds: number) => void;
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
    // Store server URL and rememberMe in localStorage (non-sensitive)
    // Token is stored in keyring separately
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      serverUrl: data.serverUrl,
      rememberMe: data.rememberMe,
      authToken: null, // Legacy: no longer stored in localStorage
    }));
    // Persist token to secure storage
    if (data.authToken && data.rememberMe) {
      saveSecureToken("auth_token", data.authToken).catch(() => {});
    } else {
      deleteSecureToken("auth_token").catch(() => {});
    }
  } catch { /* ignore */ }
}

// ─── Store ───────────────────────────────────────────

const persisted = loadPersisted();

export const useConnectionStore = create<ConnectionState>((set, get) => ({
  serverUrl: persisted.serverUrl ?? "",
  authUrl: "",
  serverInfo: null,
  connectionStatus: persisted.serverUrl ? "disconnected" : "unconfigured",
  connectionError: null,
  authToken: persisted.rememberMe ? (persisted.authToken ?? null) : null,
  rememberMe: persisted.rememberMe ?? false,
  user: null,
  org: null,
  magicLinkEmail: null,
  isDiscovering: false,
  cooldownRemaining: 0,

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
      // Test connection by hitting the server health endpoint (via Rust proxy)
      const res = await tauriFetch(`${serverUrl}/api/health`);

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      // Extract auth URL from health response (Better Auth service)
      try {
        const health = await res.json() as { auth_url?: string };
        if (health.auth_url) {
          set({ authUrl: health.auth_url });
        }
      } catch { /* ignore */ }

      // Fetch server info
      try {
        const infoRes = await tauriFetch(`${serverUrl}/api/server/info`);
        if (infoRes.ok) {
          const info = await infoRes.json() as ServerInfo;
          set({ serverInfo: info });
        }
      } catch { /* non-critical */ }

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
    const { serverUrl, authUrl } = get();
    const authBase = authUrl || serverUrl;
    set({ connectionStatus: "connecting", connectionError: null, rememberMe: remember });

    try {
      // Sign in via Better Auth
      const res = await tauriFetch(`${authBase}/api/auth/sign-in/email`, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ message: "Login failed" })) as { message?: string; code?: string };
        throw new Error(body.message || `Login failed (${res.status})`);
      }

      // Extract session token from Set-Cookie header
      let sessionToken = extractSessionToken(res.headers);
      if (!sessionToken) {
        // Fallback: try to get token from response body
        const data = await res.json() as { token?: string };
        if (!data.token) {
          throw new Error("No session token received");
        }
        sessionToken = data.token;
      }

      const token = sessionToken;

      // Fetch user profile using the session token
      const meRes = await tauriFetch(`${authBase}/api/auth/get-session`, {
        token,
      });

      let user: ForgeUser = { id: "", email, name: email.split("@")[0], role: "member", createdAt: new Date().toISOString() };
      let org: ForgeOrg | null = null;

      if (meRes.ok) {
        const session = await meRes.json() as {
          user?: { id: string; email: string; name: string };
          session?: { activeOrganizationId?: string };
        };
        if (session.user) {
          user = {
            id: session.user.id,
            email: session.user.email,
            name: session.user.name || session.user.email.split("@")[0],
            role: "member",
            createdAt: new Date().toISOString(),
          };
        }

        // Try to get org info
        const orgId = session.session?.activeOrganizationId;
        if (orgId) {
          try {
            const orgRes = await tauriFetch(`${authBase}/api/auth/organization/get-full-organization`, {
              token,
            });
            if (orgRes.ok) {
              const orgData = await orgRes.json() as { id: string; name: string; slug: string };
              org = { id: orgData.id, name: orgData.name, slug: orgData.slug, plan: "free", memberCount: 1 };
            }
          } catch { /* non-critical */ }
        }

        // If no active org, list orgs and pick the first
        if (!org) {
          try {
            const orgsRes = await tauriFetch(`${authBase}/api/auth/organization/list`, {
              token,
            });
            if (orgsRes.ok) {
              const orgs = await orgsRes.json() as Array<{ id: string; name: string; slug: string }>;
              if (Array.isArray(orgs) && orgs.length > 0) {
                org = { id: orgs[0].id, name: orgs[0].name, slug: orgs[0].slug, plan: "free", memberCount: 1 };
                // Set active org
                try {
                  await tauriFetch(`${authBase}/api/auth/organization/set-active`, {
                    method: "POST",
                    body: JSON.stringify({ organizationId: orgs[0].id }),
                    token,
                  });
                } catch { /* non-critical */ }
              }
            }
          } catch { /* non-critical */ }
        }
      }

      set({
        authToken: token,
        user,
        org,
        connectionStatus: "authenticated",
        connectionError: null,
      });

      savePersisted({
        serverUrl,
        authToken: remember ? token : null,
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

  requestMagicLink: async (email) => {
    const { serverUrl } = get();
    set({ connectionStatus: "connecting", connectionError: null });

    try {
      const res = await tauriFetch(`${serverUrl}/api/auth/magic-link`, {
        method: "POST",
        body: JSON.stringify({ email }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Request failed" })) as { detail?: string };
        throw new Error(body.detail || `Request failed (${res.status})`);
      }

      // Check for cooldown_remaining from server
      const data = await res.json().catch(() => ({})) as { cooldown_remaining?: number };
      if (data.cooldown_remaining) {
        set({ cooldownRemaining: data.cooldown_remaining });
      }

      set({
        connectionStatus: "awaiting_magic_link",
        magicLinkEmail: email,
        connectionError: null,
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to send magic link";
      set({
        connectionStatus: "connected",
        connectionError: message,
      });
      throw err;
    }
  },

  verifyMagicLink: async (token, incomingServerUrl) => {
    // If the deep link includes a server URL, use it
    const serverUrl = incomingServerUrl || get().serverUrl;
    if (incomingServerUrl && incomingServerUrl !== get().serverUrl) {
      set({ serverUrl: incomingServerUrl });
    }

    set({ connectionStatus: "connecting", connectionError: null });

    try {
      const res = await tauriFetch(`${serverUrl}/api/auth/magic-link/verify`, {
        method: "POST",
        body: JSON.stringify({ token }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Verification failed" })) as { detail?: string };
        throw new Error(body.detail || `Verification failed (${res.status})`);
      }

      const data = await res.json() as {
        session_token: string;
        user: { id: string; email: string; name: string; role: string };
        org: { id: string; name: string; slug: string } | null;
        server_url: string;
        is_new_user: boolean;
      };

      set({
        serverUrl: data.server_url || serverUrl,
        authToken: data.session_token,
        user: {
          id: data.user.id,
          email: data.user.email,
          name: data.user.name,
          role: data.user.role as "admin" | "member" | "viewer",
          createdAt: new Date().toISOString(),
        },
        org: data.org ? {
          id: data.org.id,
          name: data.org.name,
          slug: data.org.slug,
          plan: "free",
          memberCount: 1,
        } : null,
        connectionStatus: "authenticated",
        connectionError: null,
        magicLinkEmail: null,
        rememberMe: true,
      });

      savePersisted({
        serverUrl: data.server_url || serverUrl,
        authToken: data.session_token,
        rememberMe: true,
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Magic link verification failed";
      set({
        connectionStatus: "error",
        connectionError: message,
        magicLinkEmail: null,
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
      magicLinkEmail: null,
    });
    const { serverUrl } = get();
    savePersisted({ serverUrl, authToken: null, rememberMe: false });
    deleteSecureToken("auth_token").catch(() => {});
  },

  restoreSession: async () => {
    const { serverUrl, authToken } = get();
    if (!serverUrl || !authToken) return;

    set({ connectionStatus: "connecting" });

    try {
      // First, get auth URL from health endpoint
      let authBase = get().authUrl;
      if (!authBase) {
        try {
          const healthRes = await tauriFetch(`${serverUrl}/api/health`);
          if (healthRes.ok) {
            const health = await healthRes.json() as { auth_url?: string };
            if (health.auth_url) {
              authBase = health.auth_url;
              set({ authUrl: authBase });
            }
          }
        } catch { /* fall through */ }
      }
      authBase = authBase || serverUrl;

      // Validate session token against Better Auth
      const res = await tauriFetch(`${authBase}/api/auth/get-session`, {
        token: authToken,
      });

      if (!res.ok) {
        // Token expired or invalid
        set({ authToken: null, connectionStatus: "connected" });
        savePersisted({ serverUrl, authToken: null, rememberMe: false });
        return;
      }

      const session = await res.json() as {
        user?: { id: string; email: string; name: string };
        session?: { activeOrganizationId?: string };
      };

      if (!session.user) {
        set({ authToken: null, connectionStatus: "connected" });
        savePersisted({ serverUrl, authToken: null, rememberMe: false });
        return;
      }

      const user: ForgeUser = {
        id: session.user.id,
        email: session.user.email,
        name: session.user.name || session.user.email.split("@")[0],
        role: "member",
        createdAt: new Date().toISOString(),
      };

      set({
        user,
        connectionStatus: "authenticated",
      });
    } catch {
      // Server unreachable — stay disconnected but keep token for retry
      set({ connectionStatus: "disconnected" });
    }
  },

  discoverServer: async (email) => {
    const domain = email.split("@")[1];
    if (!domain) return null;

    set({ isDiscovering: true });

    const candidates = [
      `https://forge.${domain}`,
      `https://${domain}/forge`,
    ];

    try {
      for (const base of candidates) {
        try {
          const res = await tauriFetch(`${base}/api/server/info`);
          if (res.ok) {
            const info = await res.json() as ServerInfo;
            if (info?.server_url) {
              set({ isDiscovering: false });
              return info.server_url;
            }
            set({ isDiscovering: false });
            return base;
          }
        } catch {
          // Try next candidate
        }
      }
    } finally {
      set({ isDiscovering: false });
    }

    return null;
  },

  checkMagicLinkStatus: async () => {
    const { serverUrl, magicLinkEmail } = get();
    if (!serverUrl || !magicLinkEmail) {
      return { status: "not_found" as const };
    }

    try {
      const res = await tauriFetch(
        `${serverUrl}/api/auth/magic-link/status?email=${encodeURIComponent(magicLinkEmail)}`
      );
      if (res.ok) {
        return await res.json() as MagicLinkStatusResponse;
      }
    } catch {
      // Polling failure is non-critical
    }
    return { status: "not_found" as const };
  },

  initializeAuth: async () => {
    // Load auth token from secure storage (keyring)
    try {
      const token = await getSecureToken("auth_token");
      if (token) {
        set({ authToken: token });
      }
    } catch {
      // Keyring unavailable — fall back to whatever was loaded from localStorage
    }
  },

  setCooldownRemaining: (seconds) => set({ cooldownRemaining: seconds }),

  setConnectionStatus: (status) => set({ connectionStatus: status }),
  setError: (error) => set({ connectionError: error }),
}));
