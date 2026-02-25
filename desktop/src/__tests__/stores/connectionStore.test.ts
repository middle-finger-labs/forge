import { describe, it, expect, vi, beforeEach } from "vitest";
import { useConnectionStore } from "@/stores/connectionStore";

// Helper to reset store between tests
function resetStore() {
  useConnectionStore.setState({
    serverUrl: "",
    connectionStatus: "unconfigured",
    connectionError: null,
    authToken: null,
    rememberMe: false,
    user: null,
    org: null,
  });
}

const mockUser = {
  id: "u1",
  email: "admin@example.com",
  name: "Admin",
  role: "admin" as const,
  createdAt: "2024-01-01T00:00:00Z",
};

const mockOrg = {
  id: "o1",
  name: "Test Org",
  slug: "test-org",
  plan: "pro" as const,
  memberCount: 5,
};

describe("connectionStore", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  // ─── Initial state ──────────────────────────────

  it("starts with unconfigured status when no serverUrl", () => {
    const state = useConnectionStore.getState();
    expect(state.connectionStatus).toBe("unconfigured");
    expect(state.serverUrl).toBe("");
    expect(state.authToken).toBeNull();
    expect(state.user).toBeNull();
    expect(state.org).toBeNull();
  });

  // ─── setServerUrl ───────────────────────────────

  it("sets server URL and persists to localStorage", () => {
    useConnectionStore.getState().setServerUrl("http://forge.test:8000");
    const state = useConnectionStore.getState();
    expect(state.serverUrl).toBe("http://forge.test:8000");
    expect(state.connectionError).toBeNull();
    expect(localStorage.setItem).toHaveBeenCalled();
  });

  // ─── connect ────────────────────────────────────

  it("connect() succeeds when server responds 200", async () => {
    useConnectionStore.getState().setServerUrl("http://localhost:8000");

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("{}", { status: 200 })
    );

    const result = await useConnectionStore.getState().connect();
    expect(result).toBe(true);
    expect(useConnectionStore.getState().connectionStatus).toBe("connected");
  });

  it("connect() returns false when no serverUrl", async () => {
    const result = await useConnectionStore.getState().connect();
    expect(result).toBe(false);
    expect(useConnectionStore.getState().connectionError).toBe("Server URL is required");
  });

  it("connect() sets error status on network failure", async () => {
    useConnectionStore.getState().setServerUrl("http://localhost:8000");

    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const result = await useConnectionStore.getState().connect();
    expect(result).toBe(false);
    expect(useConnectionStore.getState().connectionStatus).toBe("error");
    expect(useConnectionStore.getState().connectionError).toContain("ECONNREFUSED");
  });

  it("connect() sets error on non-200 response", async () => {
    useConnectionStore.getState().setServerUrl("http://localhost:8000");

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", { status: 503 })
    );

    const result = await useConnectionStore.getState().connect();
    expect(result).toBe(false);
    expect(useConnectionStore.getState().connectionStatus).toBe("error");
  });

  // ─── login ──────────────────────────────────────

  it("login() authenticates and stores user/org", async () => {
    useConnectionStore.getState().setServerUrl("http://localhost:8000");

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ token: "jwt-xyz", user: mockUser, org: mockOrg }),
        { status: 200 }
      )
    );

    await useConnectionStore.getState().login("admin@example.com", "pass", true);
    const state = useConnectionStore.getState();

    expect(state.connectionStatus).toBe("authenticated");
    expect(state.authToken).toBe("jwt-xyz");
    expect(state.user?.email).toBe("admin@example.com");
    expect(state.org?.name).toBe("Test Org");
    expect(state.rememberMe).toBe(true);
  });

  it("login() throws on 401", async () => {
    useConnectionStore.getState().setServerUrl("http://localhost:8000");

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 })
    );

    await expect(
      useConnectionStore.getState().login("bad@user.com", "wrong", false)
    ).rejects.toThrow("Invalid credentials");

    expect(useConnectionStore.getState().connectionStatus).toBe("error");
  });

  // ─── logout ─────────────────────────────────────

  it("logout() clears auth state and reverts to connected", () => {
    useConnectionStore.setState({
      serverUrl: "http://localhost:8000",
      connectionStatus: "authenticated",
      authToken: "jwt-xyz",
      user: mockUser,
      org: mockOrg,
    });

    useConnectionStore.getState().logout();
    const state = useConnectionStore.getState();

    expect(state.connectionStatus).toBe("connected");
    expect(state.authToken).toBeNull();
    expect(state.user).toBeNull();
    expect(state.org).toBeNull();
  });

  // ─── restoreSession ─────────────────────────────

  it("restoreSession() skips if no token", async () => {
    useConnectionStore.setState({ serverUrl: "http://localhost:8000", authToken: null });
    await useConnectionStore.getState().restoreSession();
    expect(useConnectionStore.getState().connectionStatus).toBe("unconfigured");
  });

  it("restoreSession() authenticates with valid token", async () => {
    useConnectionStore.setState({
      serverUrl: "http://localhost:8000",
      authToken: "valid-token",
      connectionStatus: "disconnected",
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ user: mockUser, org: mockOrg }), { status: 200 })
    );

    await useConnectionStore.getState().restoreSession();
    const state = useConnectionStore.getState();

    expect(state.connectionStatus).toBe("authenticated");
    expect(state.user?.name).toBe("Admin");
  });

  it("restoreSession() clears token on 401", async () => {
    useConnectionStore.setState({
      serverUrl: "http://localhost:8000",
      authToken: "expired-token",
      connectionStatus: "disconnected",
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", { status: 401 })
    );

    await useConnectionStore.getState().restoreSession();
    const state = useConnectionStore.getState();

    expect(state.connectionStatus).toBe("connected");
    expect(state.authToken).toBeNull();
  });

  // ─── setConnectionStatus / setError ─────────────

  it("setConnectionStatus updates status", () => {
    useConnectionStore.getState().setConnectionStatus("connecting");
    expect(useConnectionStore.getState().connectionStatus).toBe("connecting");
  });

  it("setError updates error message", () => {
    useConnectionStore.getState().setError("Something broke");
    expect(useConnectionStore.getState().connectionError).toBe("Something broke");
  });
});
