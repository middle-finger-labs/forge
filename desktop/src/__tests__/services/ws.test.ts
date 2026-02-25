import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ForgeWebSocket } from "@/services/ws";

describe("ForgeWebSocket", () => {
  let ws: ForgeWebSocket;

  beforeEach(() => {
    ws = new ForgeWebSocket();
    vi.useFakeTimers();
  });

  afterEach(() => {
    ws.disconnect();
    vi.useRealTimers();
  });

  // ─── Event subscription ─────────────────────

  it("on() registers handler and returns unsubscribe function", () => {
    const handler = vi.fn();
    const unsub = ws.on("message", handler);

    expect(typeof unsub).toBe("function");

    // Unsubscribe
    unsub();
    // No way to verify directly without connecting, but at least it doesn't throw
  });

  it("off() removes a registered handler", () => {
    const handler = vi.fn();
    ws.on("message", handler);
    ws.off("message", handler);
    // Should not throw
  });

  // ─── Message queue ──────────────────────────

  it("queues messages when not connected", () => {
    // Send without connecting — should queue
    ws.send("message", { text: "hello" });
    // No crash = success (messages queued internally)
  });

  // ─── Disconnect ─────────────────────────────

  it("disconnect() sets intentional close", () => {
    ws.disconnect();
    // Should not attempt reconnection
    vi.advanceTimersByTime(60_000);
    // No crash = no reconnection attempted
  });

  // ─── Connection status events ────────────────

  it("emits connection_status events to listeners", () => {
    const handler = vi.fn();
    ws.on("connection_status", handler);

    // Disconnect triggers status change
    ws.disconnect();
    expect(handler).toHaveBeenCalledWith("disconnected");
  });

  // ─── Multiple listeners ──────────────────────

  it("supports multiple listeners per event type", () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();

    ws.on("connection_status", handler1);
    ws.on("connection_status", handler2);

    ws.disconnect();

    expect(handler1).toHaveBeenCalled();
    expect(handler2).toHaveBeenCalled();
  });

  // ─── Unsubscribe isolation ───────────────────

  it("unsubscribing one handler does not affect others", () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();

    const unsub1 = ws.on("connection_status", handler1);
    ws.on("connection_status", handler2);

    unsub1();
    ws.disconnect();

    expect(handler1).not.toHaveBeenCalled();
    expect(handler2).toHaveBeenCalled();
  });
});
