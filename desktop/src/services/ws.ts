import TauriWebSocket from "@tauri-apps/plugin-websocket";
import { useConnectionStore } from "@/stores/connectionStore";
import type { Message } from "@/types/message";
import type { Agent, AgentRole, AgentStatus } from "@/types/agent";
import type { PipelineEvent } from "@/types/pipeline";

// ─── Event types ─────────────────────────────────────

export interface WsEventMap {
  message: Message;
  agent_status: Agent;
  pipeline_event: PipelineEvent;
  presence: PresenceUpdate[];
  typing: { who: string; conversationId: string };
  connection_status: ConnectionStatus;
}

export interface PresenceUpdate {
  id: string;
  role?: AgentRole;
  status: AgentStatus;
}

export type ConnectionStatus = "connected" | "disconnected" | "reconnecting";

type EventHandler<K extends keyof WsEventMap> = (data: WsEventMap[K]) => void;

// ─── Incoming message envelope ───────────────────────

interface WsEnvelope {
  type: keyof WsEventMap;
  payload: unknown;
}

// ─── ForgeWebSocket ──────────────────────────────────

const INITIAL_RECONNECT_MS = 1000;
const MAX_RECONNECT_MS = 30_000;
const HEARTBEAT_INTERVAL_MS = 30_000;

export class ForgeWebSocket {
  private ws: TauriWebSocket | null = null;
  private serverUrl: string = "";
  private token: string = "";
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectDelay: number = INITIAL_RECONNECT_MS;
  private intentionalClose: boolean = false;
  private messageQueue: Array<{ type: string; payload: unknown }> = [];

  private listeners: {
    [K in keyof WsEventMap]?: Set<EventHandler<K>>;
  } = {};

  // ─── Connection lifecycle ──────────────────────────

  async connect(serverUrl: string, token: string = ""): Promise<void> {
    this.serverUrl = serverUrl;
    this.token = token;
    this.intentionalClose = false;
    await this.doConnect();
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.cleanup();
    this.setConnectionStatus("disconnected");
  }

  private async doConnect(): Promise<void> {
    this.cleanup();
    this.setConnectionStatus("reconnecting");

    const url = this.token
      ? `${this.serverUrl}?token=${encodeURIComponent(this.token)}`
      : this.serverUrl;

    try {
      this.ws = await TauriWebSocket.connect(url);
      this.reconnectDelay = INITIAL_RECONNECT_MS;
      this.setConnectionStatus("connected");
      this.startHeartbeat();
      this.flushQueue();

      this.ws.addListener((msg) => {
        if (typeof msg === "object" && msg !== null && "data" in msg) {
          const raw = msg as { data: string };
          this.handleRawMessage(raw.data);
        }
      });
    } catch {
      this.setConnectionStatus("disconnected");
      this.scheduleReconnect();
    }
  }

  private handleRawMessage(data: string): void {
    // Pong response — ignore
    if (data === "pong") return;

    let envelope: WsEnvelope;
    try {
      envelope = JSON.parse(data) as WsEnvelope;
    } catch {
      return;
    }

    const handlers = this.listeners[envelope.type];
    if (handlers) {
      // The cast is safe because the envelope type key matches the handler type
      for (const handler of handlers) {
        (handler as EventHandler<typeof envelope.type>)(
          envelope.payload as WsEventMap[typeof envelope.type]
        );
      }
    }
  }

  // ─── Reconnection ─────────────────────────────────

  private scheduleReconnect(): void {
    if (this.intentionalClose) return;

    this.reconnectTimer = setTimeout(() => {
      this.doConnect();
    }, this.reconnectDelay);

    // Exponential backoff: 1s → 2s → 4s → 8s → … → 30s
    this.reconnectDelay = Math.min(
      this.reconnectDelay * 2,
      MAX_RECONNECT_MS
    );
  }

  // ─── Heartbeat ────────────────────────────────────

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws) {
        this.ws.send("ping");
      }
    }, HEARTBEAT_INTERVAL_MS);
  }

  // ─── Cleanup ──────────────────────────────────────

  private cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.ws) {
      this.ws.disconnect();
      this.ws = null;
    }
  }

  // ─── Event subscriptions ──────────────────────────

  on<K extends keyof WsEventMap>(
    event: K,
    handler: EventHandler<K>
  ): () => void {
    if (!this.listeners[event]) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (this.listeners as any)[event] = new Set();
    }
    const set = this.listeners[event]!;
    set.add(handler);
    return () => {
      set.delete(handler);
    };
  }

  off<K extends keyof WsEventMap>(
    event: K,
    handler: EventHandler<K>
  ): void {
    this.listeners[event]?.delete(handler);
  }

  // ─── Send ─────────────────────────────────────────

  send(type: string, payload: unknown): void {
    const data = JSON.stringify({ type, payload });
    if (this.ws) {
      this.ws.send(data);
    } else {
      // Queue while disconnected
      this.messageQueue.push({ type, payload });
    }
  }

  private flushQueue(): void {
    while (this.messageQueue.length > 0) {
      const item = this.messageQueue.shift()!;
      this.send(item.type, item.payload);
    }
  }

  // ─── Connection status ────────────────────────────

  private setConnectionStatus(status: ConnectionStatus): void {
    const store = useConnectionStore.getState();
    store.setConnectionStatus(
      status === "reconnecting" ? "connecting" : status
    );

    const handlers = this.listeners["connection_status"];
    if (handlers) {
      for (const handler of handlers) {
        (handler as EventHandler<"connection_status">)(status);
      }
    }
  }
}

// ─── Singleton ────────────────────────────────────────

let _instance: ForgeWebSocket | null = null;

export function getForgeWS(): ForgeWebSocket {
  if (!_instance) {
    _instance = new ForgeWebSocket();
  }
  return _instance;
}
