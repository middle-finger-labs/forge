import { describe, it, expect, vi, beforeEach } from "vitest";
import { ForgeAPI, ApiError } from "@/services/api";

describe("ForgeAPI", () => {
  let api: ForgeAPI;

  beforeEach(() => {
    api = new ForgeAPI("http://localhost:8000", "test-token");
    vi.restoreAllMocks();
  });

  // ─── Constructor / factory ────────────────────

  it("creates instance with base URL and token", () => {
    expect(api).toBeInstanceOf(ForgeAPI);
  });

  it("static create() resolves URL from Tauri invoke", async () => {
    const instance = await ForgeAPI.create("tk");
    expect(instance).toBeInstanceOf(ForgeAPI);
  });

  it("wsUrl converts http to ws", () => {
    expect(api.wsUrl).toBe("ws://localhost:8000/ws");
  });

  it("wsUrl converts https to wss", () => {
    const secureApi = new ForgeAPI("https://forge.example.com");
    expect(secureApi.wsUrl).toBe("wss://forge.example.com/ws");
  });

  // ─── Conversations ───────────────────────────

  it("getConversations() makes GET request", async () => {
    const mockConvs = [{ id: "c1", type: "agent_dm", title: "DM" }];
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockConvs), { status: 200 })
    );

    const result = await api.getConversations();
    expect(result).toEqual(mockConvs);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/conversations",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      })
    );
  });

  it("getMessages() supports cursor pagination", async () => {
    const mockData = { messages: [], nextCursor: "abc" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockData), { status: 200 })
    );

    await api.getMessages("conv-1", "prev-cursor");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/conversations/conv-1/messages?cursor=prev-cursor",
      expect.anything()
    );
  });

  it("sendMessage() sends POST with content", async () => {
    const mockMsg = { id: "m1" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockMsg), { status: 200 })
    );

    const content = [{ type: "text" as const, text: "Hello" }];
    await api.sendMessage("conv-1", content);

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/conversations/conv-1/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ content }),
      })
    );
  });

  // ─── Agent DMs ───────────────────────────────

  it("sendAgentMessage() sends to correct agent endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "m1" }), { status: 200 })
    );

    await api.sendAgentMessage("engineer", "Help me with auth");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/agents/engineer/message",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "Help me with auth" }),
      })
    );
  });

  // ─── Pipelines ──────────────────────────────

  it("createPipeline() sends spec and name", async () => {
    const mockPipeline = { id: "p1", status: "pending" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockPipeline), { status: 200 })
    );

    const result = await api.createPipeline("Build a URL shortener", "shortener");
    expect(result).toEqual(mockPipeline);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/pipelines",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ spec: "Build a URL shortener", name: "shortener" }),
      })
    );
  });

  it("approvePipeline() sends approval signal", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 204 })
    );

    await api.approvePipeline("p1", "architecture", true, "Looks good");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/pipelines/p1/approve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ stage: "architecture", approved: true, comment: "Looks good" }),
      })
    );
  });

  // ─── Error handling ─────────────────────────

  it("throws ApiError on non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("Not Found", { status: 404, statusText: "Not Found" })
    );

    await expect(api.getConversations()).rejects.toThrow(ApiError);
    await expect(api.getConversations()).rejects.toThrow(); // fetch mock consumed

    // Verify a fresh ApiError has the right shape
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("Unauthorized", { status: 401, statusText: "Unauthorized" })
    );

    try {
      await api.getConversations();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(401);
      expect(apiErr.statusText).toBe("Unauthorized");
    }
  });

  // ─── Token management ──────────────────────

  it("setToken updates authorization header", async () => {
    api.setToken("new-token");

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("[]", { status: 200 })
    );

    await api.getConversations();
    expect(fetch).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer new-token",
        }),
      })
    );
  });

  it("omits Authorization header when no token", async () => {
    const noAuthApi = new ForgeAPI("http://localhost:8000");

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("[]", { status: 200 })
    );

    await noAuthApi.getConversations();
    const callHeaders = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][1]?.headers;
    expect(callHeaders?.Authorization).toBeUndefined();
  });
});
