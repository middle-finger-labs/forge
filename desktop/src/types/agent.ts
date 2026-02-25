export type AgentRole =
  | "ba"
  | "researcher"
  | "architect"
  | "pm"
  | "engineer"
  | "qa"
  | "cto";

export type AgentStatus =
  | "idle"
  | "working"
  | "waiting"
  | "error"
  | "offline";

export interface Agent {
  role: AgentRole;
  displayName: string;
  emoji: string;
  status: AgentStatus;
  currentTask?: string;
  lastActive?: string;
}

/** Static registry of agent display info */
export const AGENT_REGISTRY: Record<AgentRole, { displayName: string; emoji: string }> = {
  ba:         { displayName: "Business Analyst", emoji: "\u{1F3E2}" },
  researcher: { displayName: "Researcher",       emoji: "\u{1F52C}" },
  architect:  { displayName: "Architect",         emoji: "\u{1F3D7}\uFE0F" },
  pm:         { displayName: "PM",                emoji: "\u{1F4CB}" },
  engineer:   { displayName: "Engineer",          emoji: "\u{1F4BB}" },
  qa:         { displayName: "QA",                emoji: "\u{1F9EA}" },
  cto:        { displayName: "CTO",               emoji: "\u{1F454}" },
};

export const AGENT_ROLES: AgentRole[] = [
  "ba",
  "researcher",
  "architect",
  "pm",
  "engineer",
  "qa",
  "cto",
];
