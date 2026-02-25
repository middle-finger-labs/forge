import { invoke } from "@tauri-apps/api/core";
import type { Conversation } from "@/types/conversation";
import type { Message, MessageContent } from "@/types/message";
import type { Agent, AgentRole } from "@/types/agent";
import type { PipelineRun } from "@/types/pipeline";
import type {
  PromptVersion,
  PromptVersionStats,
  StatsHistoryPoint,
  CompareResult,
  DefaultPrompt,
  TestPromptResult,
  Lesson,
  UpdateLessonRequest,
  PipelineSummary,
} from "@/types/prompts";
import type {
  Repository,
  FileNode,
  RepoChunk,
  RepoSearchResult,
  DependencyEdge,
} from "@/types/repository";

export interface PaginatedMessages {
  messages: Message[];
  nextCursor?: string;
}

export interface TeamMember {
  id: string;
  email: string;
  name: string;
  role: string;
  joined_at: string | null;
}

export interface PendingInvite {
  email: string;
  invited_by: string | null;
  created_at: string | null;
  expires_at: string | null;
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

  // ─── Prompts ─────────────────────────────────────────

  async getPromptVersions(stage: number): Promise<PromptVersion[]> {
    return this.request<PromptVersion[]>(
      `/api/prompts/versions?stage=${stage}`
    );
  }

  async createPromptVersion(req: {
    stage: number;
    system_prompt: string;
    change_summary?: string;
    activate?: boolean;
  }): Promise<PromptVersion> {
    return this.request<PromptVersion>("/api/prompts/versions", {
      method: "POST",
      body: JSON.stringify(req),
    });
  }

  async getPromptVersion(id: string): Promise<PromptVersion> {
    return this.request<PromptVersion>(`/api/prompts/versions/${id}`);
  }

  async activatePromptVersion(id: string): Promise<void> {
    return this.request<void>(`/api/prompts/versions/${id}/activate`, {
      method: "PUT",
    });
  }

  async getPromptVersionStats(id: string): Promise<PromptVersionStats> {
    return this.request<PromptVersionStats>(
      `/api/prompts/versions/${id}/stats`
    );
  }

  async getPromptVersionStatsHistory(
    id: string
  ): Promise<StatsHistoryPoint[]> {
    return this.request<StatsHistoryPoint[]>(
      `/api/prompts/versions/${id}/stats/history`
    );
  }

  async comparePromptVersions(a: string, b: string): Promise<CompareResult> {
    return this.request<CompareResult>("/api/prompts/compare", {
      method: "POST",
      body: JSON.stringify({ version_a: a, version_b: b }),
    });
  }

  async getDefaultPrompts(): Promise<DefaultPrompt[]> {
    return this.request<DefaultPrompt[]>("/api/prompts/defaults");
  }

  async testPrompt(
    stage: number,
    systemPrompt: string,
    sampleInput?: string
  ): Promise<TestPromptResult> {
    return this.request<TestPromptResult>("/api/prompts/test", {
      method: "POST",
      body: JSON.stringify({
        stage,
        system_prompt: systemPrompt,
        sample_input: sampleInput,
      }),
    });
  }

  // ─── Lessons ─────────────────────────────────────────

  async getLessons(agentRole?: string): Promise<Lesson[]> {
    const params = agentRole ? `?agent_role=${agentRole}` : "";
    return this.request<Lesson[]>(`/api/lessons${params}`);
  }

  async updateLesson(
    id: string,
    data: UpdateLessonRequest
  ): Promise<Lesson> {
    return this.request<Lesson>(`/api/lessons/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async deleteLesson(id: string): Promise<void> {
    return this.request<void>(`/api/lessons/${id}`, {
      method: "DELETE",
    });
  }

  async reinforceLesson(id: string): Promise<Lesson> {
    return this.request<Lesson>(`/api/lessons/${id}/reinforce`, {
      method: "POST",
    });
  }

  // ─── Pipeline summary ───────────────────────────────

  async getPipelineSummary(pipelineId: string): Promise<PipelineSummary> {
    return this.request<PipelineSummary>(
      `/api/pipelines/${pipelineId}/summary`
    );
  }

  // ─── Repositories ─────────────────────────────────────

  async getRepos(): Promise<Repository[]> {
    return this.request<Repository[]>("/api/repos");
  }

  async indexRepo(source: string, sourceType: "git" | "local"): Promise<Repository> {
    return this.request<Repository>("/api/repos", {
      method: "POST",
      body: JSON.stringify({ source, source_type: sourceType }),
    });
  }

  async reindexRepo(repoId: string): Promise<Repository> {
    return this.request<Repository>(`/api/repos/${repoId}/reindex`, {
      method: "POST",
    });
  }

  async deleteRepo(repoId: string): Promise<void> {
    return this.request<void>(`/api/repos/${repoId}`, {
      method: "DELETE",
    });
  }

  async getRepoFileTree(repoId: string): Promise<FileNode[]> {
    return this.request<FileNode[]>(`/api/repos/${repoId}/tree`);
  }

  async getRepoFileChunks(repoId: string, filePath: string): Promise<RepoChunk[]> {
    return this.request<RepoChunk[]>(
      `/api/repos/${repoId}/chunks?path=${encodeURIComponent(filePath)}`
    );
  }

  async searchRepo(repoId: string, query: string): Promise<RepoSearchResult[]> {
    return this.request<RepoSearchResult[]>(
      `/api/repos/${repoId}/search`,
      {
        method: "POST",
        body: JSON.stringify({ query }),
      }
    );
  }

  async getRepoDependencies(repoId: string): Promise<DependencyEdge[]> {
    return this.request<DependencyEdge[]>(`/api/repos/${repoId}/dependencies`);
  }

  // ─── Team ────────────────────────────────────────────

  async getTeamMembers(): Promise<TeamMember[]> {
    return this.request<TeamMember[]>("/api/auth/team/members");
  }

  async getPendingInvites(): Promise<PendingInvite[]> {
    return this.request<PendingInvite[]>("/api/auth/team/invites");
  }

  async sendInvite(email: string, role: string = "member"): Promise<{ message: string; email: string }> {
    return this.request<{ message: string; email: string }>("/api/auth/invite", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    });
  }

  /** Send a message to an agent with codebase context */
  async sendAgentMessageWithContext(
    agentRole: AgentRole,
    message: string,
    repoId: string
  ): Promise<Message> {
    return this.request<Message>(`/api/agents/${agentRole}/message`, {
      method: "POST",
      body: JSON.stringify({ message, repo_id: repoId }),
    });
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
