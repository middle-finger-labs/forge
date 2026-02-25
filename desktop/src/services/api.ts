import { invoke } from "@tauri-apps/api/core";
import type { Conversation } from "@/types/conversation";
import type { Message, MessageContent } from "@/types/message";
import type { Agent, AgentRole } from "@/types/agent";
import type { PipelineRun } from "@/types/pipeline";

export interface PaginatedMessages {
  messages: Message[];
  nextCursor?: string;
}

export interface CreatePipelineRequest {
  spec: string;
  name?: string;
}

export class ForgeAPI {
  private baseUrl: string;
  private token: string;

  constructor(baseUrl: string, token: string = "") {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  /** Resolve the base URL from the Tauri backend */
  static async create(token: string = ""): Promise<ForgeAPI> {
    const baseUrl = await invoke<string>("get_forge_api_url");
    return new ForgeAPI(baseUrl, token);
  }

  setToken(token: string) {
    this.token = token;
  }

  get wsUrl(): string {
    return this.baseUrl.replace(/^http/, "ws") + "/ws";
  }

  // ─── HTTP helpers ────────────────────────────────────

  private async request<T>(
    path: string,
    options?: RequestInit
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: { ...headers, ...options?.headers },
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new ApiError(res.status, res.statusText, body);
    }

    // 204 No Content
    if (res.status === 204) {
      return undefined as T;
    }

    return res.json();
  }

  // ─── Conversations ──────────────────────────────────

  async getConversations(): Promise<Conversation[]> {
    return this.request<Conversation[]>("/api/conversations");
  }

  async getMessages(
    conversationId: string,
    cursor?: string
  ): Promise<PaginatedMessages> {
    const params = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    return this.request<PaginatedMessages>(
      `/api/conversations/${conversationId}/messages${params}`
    );
  }

  async sendMessage(
    conversationId: string,
    content: MessageContent[]
  ): Promise<Message> {
    return this.request<Message>(
      `/api/conversations/${conversationId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ content }),
      }
    );
  }

  // ─── Agent DMs ──────────────────────────────────────

  async sendAgentMessage(
    agentRole: AgentRole,
    message: string
  ): Promise<Message> {
    return this.request<Message>(`/api/agents/${agentRole}/message`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
  }

  // ─── Pipelines ──────────────────────────────────────

  async getPipelines(): Promise<PipelineRun[]> {
    return this.request<PipelineRun[]>("/api/pipelines");
  }

  async createPipeline(spec: string, name?: string): Promise<PipelineRun> {
    return this.request<PipelineRun>("/api/pipelines", {
      method: "POST",
      body: JSON.stringify({ spec, name }),
    });
  }

  async approvePipeline(
    pipelineId: string,
    stage: string,
    approved: boolean,
    comment?: string
  ): Promise<void> {
    return this.request<void>(
      `/api/pipelines/${pipelineId}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ stage, approved, comment }),
      }
    );
  }

  // ─── Agents ─────────────────────────────────────────

  async getAgentStatuses(): Promise<Agent[]> {
    return this.request<Agent[]>("/api/agents/status");
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: string
  ) {
    super(`API ${status}: ${statusText}`);
    this.name = "ApiError";
  }
}

// Singleton — initialized lazily
let _instance: ForgeAPI | null = null;

export async function getForgeAPI(): Promise<ForgeAPI> {
  if (!_instance) {
    _instance = await ForgeAPI.create();
  }
  return _instance;
}

export function resetForgeAPI(): void {
  _instance = null;
}

export function getForgeAPISync(baseUrl: string, token?: string): ForgeAPI {
  _instance = new ForgeAPI(baseUrl, token ?? "");
  return _instance;
}
