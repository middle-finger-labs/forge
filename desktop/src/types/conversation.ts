import type { AgentRole } from "./agent";
import type { Message } from "./message";

export type ConversationType = "agent_dm" | "pipeline" | "general";

export interface Participant {
  type: "user" | "agent";
  id: string;
  role?: AgentRole;
  name: string;
}

export interface Conversation {
  id: string;
  type: ConversationType;
  title: string;
  agentRole?: AgentRole;
  pipelineId?: string;
  lastMessage?: Message;
  unreadCount: number;
  participants: Participant[];
  createdAt: string;
  updatedAt: string;
}
