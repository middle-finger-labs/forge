import type { AgentRole } from "./agent";

// ─── Author ──────────────────────────────────────────────

export type MessageAuthor =
  | { type: "user"; userId: string; name: string }
  | { type: "agent"; role: AgentRole; name: string }
  | { type: "system" };

// ─── Content blocks ──────────────────────────────────────

export type MessageContent =
  | { type: "text"; text: string }
  | { type: "markdown"; markdown: string }
  | { type: "code"; language: string; code: string; filename?: string }
  | { type: "diff"; diff: string; filename: string }
  | {
      type: "approval_request";
      stage: string;
      summary: string;
      approvalId: string;
    }
  | {
      type: "approval_response";
      approved: boolean;
      comment?: string;
    }
  | {
      type: "file_attachment";
      filename: string;
      url: string;
      size: number;
    }
  | {
      type: "pipeline_event";
      event: string;
      details: Record<string, unknown>;
    }
  | {
      type: "cost_update";
      totalCost: number;
      breakdown: Record<string, number>;
    }
  | {
      type: "pipeline_summary";
      pipelineId: string;
      totalCost: number;
      totalDuration: number;
      perAgent: Record<
        string,
        {
          cost: number;
          duration: number;
          firstPass: boolean;
          attempts: number;
          lessonsApplied: number;
        }
      >;
      lessonsApplied: Array<{ agentRole: string; lesson: string }>;
    }
  | {
      type: "code_reference";
      filePath: string;
      startLine: number;
      endLine?: number;
      repoId: string;
      repoName: string;
      snippet?: string;
      language?: string;
    };

// ─── Reactions ───────────────────────────────────────────

export interface Reaction {
  emoji: string;
  users: string[];
}

// ─── Message ─────────────────────────────────────────────

export interface Message {
  id: string;
  conversationId: string;
  author: MessageAuthor;
  content: MessageContent[];
  threadId?: string;
  reactions?: Reaction[];
  createdAt: string;
}
