import type { Agent, AgentRole } from "@/types/agent";
import { AGENT_REGISTRY, AGENT_ROLES } from "@/types/agent";
import type { Conversation, Participant } from "@/types/conversation";
import type { Message } from "@/types/message";
import type { PipelineRun } from "@/types/pipeline";
import type { Repository, FileNode } from "@/types/repository";

// ─── Agents ──────────────────────────────────────────

export const MOCK_AGENTS: Agent[] = AGENT_ROLES.map((role) => ({
  role,
  displayName: AGENT_REGISTRY[role].displayName,
  emoji: AGENT_REGISTRY[role].emoji,
  status: (
    {
      ba: "idle",
      researcher: "idle",
      architect: "working",
      pm: "idle",
      engineer: "offline",
      qa: "offline",
      cto: "idle",
    } as Record<AgentRole, Agent["status"]>
  )[role],
  currentTask: role === "architect" ? "Designing auth system architecture" : undefined,
}));

// ─── Helpers ─────────────────────────────────────────

function agentParticipant(role: AgentRole): Participant {
  const info = AGENT_REGISTRY[role];
  return { type: "agent", id: role, role, name: info.displayName };
}

const USER_PARTICIPANT: Participant = {
  type: "user",
  id: "user-1",
  name: "You",
};

const ALL_AGENT_PARTICIPANTS: Participant[] = AGENT_ROLES.map(agentParticipant);

// ─── Conversations ───────────────────────────────────

export const MOCK_CONVERSATIONS: Conversation[] = [
  // Agent DMs
  ...AGENT_ROLES.map((role): Conversation => ({
    id: `dm-${role}`,
    type: "agent_dm",
    title: AGENT_REGISTRY[role].displayName,
    agentRole: role,
    unreadCount: 0,
    participants: [USER_PARTICIPANT, agentParticipant(role)],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  })),

  // Pipeline channels
  {
    id: "pipeline-auth",
    type: "pipeline",
    title: "auth-system-redesign",
    pipelineId: "run-auth-001",
    unreadCount: 3,
    participants: [USER_PARTICIPANT, ...ALL_AGENT_PARTICIPANTS],
    createdAt: new Date(Date.now() - 3600000).toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "pipeline-dashboard",
    type: "pipeline",
    title: "dashboard-v2",
    pipelineId: "run-dash-001",
    unreadCount: 0,
    participants: [USER_PARTICIPANT, ...ALL_AGENT_PARTICIPANTS],
    createdAt: new Date(Date.now() - 86400000).toISOString(),
    updatedAt: new Date(Date.now() - 7200000).toISOString(),
  },
  {
    id: "pipeline-api",
    type: "pipeline",
    title: "api-rate-limiting",
    pipelineId: "run-api-001",
    unreadCount: 1,
    participants: [USER_PARTICIPANT, ...ALL_AGENT_PARTICIPANTS],
    createdAt: new Date(Date.now() - 172800000).toISOString(),
    updatedAt: new Date(Date.now() - 43200000).toISOString(),
  },
];

// ─── Pipeline runs ───────────────────────────────────

export const MOCK_PIPELINE_RUNS: PipelineRun[] = [
  {
    id: "run-auth-001",
    name: "auth-system-redesign",
    status: "running",
    spec: "Redesign the authentication system with OAuth2, session management, RBAC, and MFA support.",
    startedAt: new Date(Date.now() - 3600000).toISOString(),
    cost: {
      total: 1.247,
      budget: 5.0,
      perAgent: {
        ba: 0.312,
        researcher: 0.485,
        architect: 0.45,
      },
    },
    steps: [
      { id: "s1", name: "BA", agentRole: "ba", status: "completed", dependsOn: [], startedAt: new Date(Date.now() - 3600000).toISOString(), completedAt: new Date(Date.now() - 3000000).toISOString(), cost: 0.312 },
      { id: "s2", name: "Researcher", agentRole: "researcher", status: "completed", dependsOn: ["s1"], startedAt: new Date(Date.now() - 3000000).toISOString(), completedAt: new Date(Date.now() - 2400000).toISOString(), cost: 0.485 },
      { id: "s3", name: "Architect", agentRole: "architect", status: "running", dependsOn: ["s2"], startedAt: new Date(Date.now() - 2400000).toISOString(), cost: 0.45 },
      { id: "s4", name: "PM", agentRole: "pm", status: "pending", dependsOn: ["s3"] },
      { id: "s5", name: "Engineer", agentRole: "engineer", status: "pending", dependsOn: ["s4"] },
      { id: "s6", name: "QA", agentRole: "qa", status: "pending", dependsOn: ["s5"] },
      { id: "s7", name: "CTO", agentRole: "cto", status: "pending", dependsOn: ["s6"] },
    ],
  },
  {
    id: "run-dash-001",
    name: "dashboard-v2",
    status: "completed",
    spec: "Build a new admin dashboard with real-time metrics, user management, and audit logs.",
    startedAt: new Date(Date.now() - 86400000).toISOString(),
    completedAt: new Date(Date.now() - 7200000).toISOString(),
    cost: {
      total: 3.82,
      budget: 5.0,
      perAgent: {
        ba: 0.28,
        researcher: 0.41,
        architect: 0.52,
        pm: 0.31,
        engineer: 1.64,
        qa: 0.42,
        cto: 0.24,
      },
    },
    steps: [
      { id: "s1", name: "BA", agentRole: "ba", status: "completed", dependsOn: [], cost: 0.28 },
      { id: "s2", name: "Researcher", agentRole: "researcher", status: "completed", dependsOn: ["s1"], cost: 0.41 },
      { id: "s3", name: "Architect", agentRole: "architect", status: "completed", dependsOn: ["s2"], cost: 0.52 },
      { id: "s4", name: "PM", agentRole: "pm", status: "completed", dependsOn: ["s3"], cost: 0.31 },
      { id: "s5", name: "Engineer", agentRole: "engineer", status: "completed", dependsOn: ["s4"], cost: 1.64 },
      { id: "s6", name: "QA", agentRole: "qa", status: "completed", dependsOn: ["s5"], cost: 0.42 },
      { id: "s7", name: "CTO", agentRole: "cto", status: "completed", dependsOn: ["s6"], cost: 0.24 },
    ],
  },
  {
    id: "run-api-001",
    name: "api-rate-limiting",
    status: "failed",
    spec: "Implement API rate limiting with Redis-backed sliding window and per-tenant quotas.",
    startedAt: new Date(Date.now() - 172800000).toISOString(),
    cost: {
      total: 2.15,
      budget: 3.0,
      perAgent: {
        ba: 0.22,
        researcher: 0.38,
        architect: 0.45,
        pm: 0.28,
        engineer: 0.82,
      },
    },
    steps: [
      { id: "s1", name: "BA", agentRole: "ba", status: "completed", dependsOn: [], cost: 0.22 },
      { id: "s2", name: "Researcher", agentRole: "researcher", status: "completed", dependsOn: ["s1"], cost: 0.38 },
      { id: "s3", name: "Architect", agentRole: "architect", status: "completed", dependsOn: ["s2"], cost: 0.45 },
      { id: "s4", name: "PM", agentRole: "pm", status: "completed", dependsOn: ["s3"], cost: 0.28 },
      { id: "s5", name: "Engineer", agentRole: "engineer", status: "failed", dependsOn: ["s4"], cost: 0.82 },
      { id: "s6", name: "QA", agentRole: "qa", status: "skipped", dependsOn: ["s5"] },
      { id: "s7", name: "CTO", agentRole: "cto", status: "skipped", dependsOn: ["s6"] },
    ],
  },
];

// ─── Sample messages (multi-content blocks) ──────────

export const MOCK_MESSAGES: Record<string, Message[]> = {
  "pipeline-auth": [
    // Pipeline start system message
    {
      id: "msg-0",
      conversationId: "pipeline-auth",
      author: { type: "system" },
      content: [
        {
          type: "pipeline_event",
          event: "pipeline_started",
          details: { pipeline: "auth-system-redesign" },
        },
      ],
      createdAt: new Date(Date.now() - 3600000).toISOString(),
    },
    // BA analysis
    {
      id: "msg-1",
      conversationId: "pipeline-auth",
      author: { type: "agent", role: "ba", name: "Business Analyst" },
      content: [
        { type: "text", text: "I've completed the requirements analysis for the auth system redesign." },
        {
          type: "markdown",
          markdown: "## Key Requirements\n\n- **OAuth2 + OIDC** support for Google, GitHub, Microsoft\n- **Session management** with JWT + refresh tokens\n- **RBAC** with workspace-level permissions\n- **MFA** support (TOTP + WebAuthn)\n\nFull spec attached below.",
        },
        { type: "file_attachment", filename: "auth-requirements-v1.md", url: "/files/auth-req.md", size: 14200 },
      ],
      createdAt: new Date(Date.now() - 3540000).toISOString(),
    },
    // BA stage complete
    {
      id: "msg-1b",
      conversationId: "pipeline-auth",
      author: { type: "system" },
      content: [
        {
          type: "pipeline_event",
          event: "step_completed",
          details: { step: "BA", pipeline: "auth-system-redesign" },
        },
      ],
      createdAt: new Date(Date.now() - 3000000).toISOString(),
    },
    // Research stage start
    {
      id: "msg-1c",
      conversationId: "pipeline-auth",
      author: { type: "system" },
      content: [
        {
          type: "pipeline_event",
          event: "step_started",
          details: { step: "Researcher", pipeline: "auth-system-redesign" },
        },
      ],
      createdAt: new Date(Date.now() - 3000000).toISOString(),
    },
    // Researcher analysis
    {
      id: "msg-2",
      conversationId: "pipeline-auth",
      author: { type: "agent", role: "researcher", name: "Researcher" },
      content: [
        { type: "text", text: "Finished researching auth providers. Here's my analysis:" },
        {
          type: "code",
          language: "markdown",
          code: "| Provider   | OAuth2 | OIDC | PKCE | Cost    |\n|------------|--------|------|------|---------|\n| Auth0      | \u2705     | \u2705   | \u2705   | $$$     |\n| Clerk      | \u2705     | \u2705   | \u2705   | $$      |\n| Better Auth| \u2705     | \u2705   | \u2705   | Free    |\n| Supabase   | \u2705     | \u26A0\uFE0F   | \u2705   | Free    |",
          filename: "provider-comparison.md",
        },
        { type: "text", text: "Recommendation: **Better Auth** \u2014 already in our stack, zero cost, full OIDC compliance." },
      ],
      createdAt: new Date(Date.now() - 2700000).toISOString(),
    },
    // Researcher complete
    {
      id: "msg-2b",
      conversationId: "pipeline-auth",
      author: { type: "system" },
      content: [
        {
          type: "pipeline_event",
          event: "step_completed",
          details: { step: "Researcher", pipeline: "auth-system-redesign" },
        },
      ],
      createdAt: new Date(Date.now() - 2400000).toISOString(),
    },
    // Architect stage start
    {
      id: "msg-2c",
      conversationId: "pipeline-auth",
      author: { type: "system" },
      content: [
        {
          type: "pipeline_event",
          event: "step_started",
          details: { step: "Architect", pipeline: "auth-system-redesign" },
        },
      ],
      createdAt: new Date(Date.now() - 2400000).toISOString(),
    },
    // Architect working
    {
      id: "msg-3",
      conversationId: "pipeline-auth",
      author: { type: "agent", role: "architect", name: "Architect" },
      content: [
        { type: "text", text: "Working on the architecture now. Initial thoughts on the token flow:" },
        {
          type: "code",
          language: "typescript",
          code: "// Auth flow\n// 1. User hits /auth/login \u2192 redirect to provider\n// 2. Provider callback \u2192 /auth/callback\n// 3. Server validates, creates session\n// 4. Returns JWT (15min) + refresh token (7d)\n// 5. Client stores in httpOnly cookie\n\ninterface AuthSession {\n  userId: string;\n  workspaceId: string;\n  roles: string[];\n  expiresAt: number;\n}",
          filename: "auth-flow.ts",
        },
      ],
      createdAt: new Date(Date.now() - 2100000).toISOString(),
    },
    // User intervention during Architect stage
    {
      id: "msg-4",
      conversationId: "pipeline-auth",
      author: { type: "user", userId: "me", name: "You" },
      content: [
        { type: "text", text: "Use PostgreSQL for session storage, not Redis. We want sessions to survive Redis restarts." },
      ],
      createdAt: new Date(Date.now() - 1800000).toISOString(),
    },
    // Architect acknowledges
    {
      id: "msg-5",
      conversationId: "pipeline-auth",
      author: { type: "agent", role: "architect", name: "Architect" },
      content: [
        { type: "text", text: "Good call. I'll update the architecture to use PostgreSQL for session persistence with a `sessions` table. Redis will only be used for short-lived caches (rate limiting, email verification tokens)." },
        {
          type: "code",
          language: "sql",
          code: "CREATE TABLE sessions (\n  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n  user_id UUID NOT NULL REFERENCES users(id),\n  token_hash TEXT NOT NULL UNIQUE,\n  expires_at TIMESTAMPTZ NOT NULL,\n  created_at TIMESTAMPTZ DEFAULT now(),\n  ip_address INET,\n  user_agent TEXT\n);\n\nCREATE INDEX idx_sessions_user ON sessions(user_id);\nCREATE INDEX idx_sessions_expires ON sessions(expires_at);",
          filename: "sessions-migration.sql",
        },
      ],
      createdAt: new Date(Date.now() - 1500000).toISOString(),
    },
    // Approval request
    {
      id: "msg-6",
      conversationId: "pipeline-auth",
      author: { type: "system" },
      content: [
        {
          type: "pipeline_event",
          event: "approval_needed",
          details: { step: "Architect", pipeline: "auth-system-redesign" },
        },
      ],
      createdAt: new Date(Date.now() - 900000).toISOString(),
    },
    {
      id: "msg-7",
      conversationId: "pipeline-auth",
      author: { type: "agent", role: "architect", name: "Architect" },
      content: [
        {
          type: "approval_request",
          stage: "Architecture Review",
          summary: "Architecture design is complete. OAuth2 + Better Auth, PostgreSQL sessions, RBAC with workspace permissions, MFA via TOTP + WebAuthn. Ready for PM to create tickets.",
          approvalId: "approval-arch-001",
        },
      ],
      createdAt: new Date(Date.now() - 900000).toISOString(),
    },
  ],
};

// ─── Activity events ─────────────────────────────────

export interface ActivityEvent {
  id: string;
  type: "message" | "status_change" | "approval_request" | "error";
  agentRole: AgentRole;
  pipelineId?: string;
  summary: string;
  timestamp: string;
}

export const MOCK_ACTIVITY: ActivityEvent[] = [
  {
    id: "evt-0",
    type: "approval_request",
    agentRole: "architect",
    pipelineId: "pipeline-auth",
    summary: "Architecture review awaiting approval",
    timestamp: new Date(Date.now() - 900000).toISOString(),
  },
  {
    id: "evt-1",
    type: "status_change",
    agentRole: "architect",
    pipelineId: "pipeline-auth",
    summary: "Architect started working on auth-system-redesign",
    timestamp: new Date(Date.now() - 2400000).toISOString(),
  },
  {
    id: "evt-2",
    type: "message",
    agentRole: "researcher",
    pipelineId: "pipeline-auth",
    summary: "Researcher completed analysis of OAuth2 providers",
    timestamp: new Date(Date.now() - 2700000).toISOString(),
  },
  {
    id: "evt-3",
    type: "message",
    agentRole: "ba",
    pipelineId: "pipeline-auth",
    summary: "BA delivered requirements document",
    timestamp: new Date(Date.now() - 3600000).toISOString(),
  },
  {
    id: "evt-4",
    type: "error",
    agentRole: "engineer",
    pipelineId: "pipeline-api",
    summary: "Engineer hit rate limit on external API during testing",
    timestamp: new Date(Date.now() - 43200000).toISOString(),
  },
];

// ─── Repositories ───────────────────────────────────

export const MOCK_REPOS: Repository[] = [
  {
    id: "repo-forge-api",
    name: "forge-api",
    source: "https://github.com/middlefingerlabs/forge-api.git",
    sourceType: "git",
    indexingStatus: "ready",
    lastIndexedAt: new Date(Date.now() - 7200000).toISOString(), // 2h ago
    chunkCount: 1847,
    languages: ["TypeScript", "SQL", "YAML"],
    fileCount: 234,
    localPath: "/Users/homebase/repos/forge-api",
    defaultBranch: "main",
  },
  {
    id: "repo-forge-desktop",
    name: "forge-desktop",
    source: "/Users/homebase/forge/desktop",
    sourceType: "local",
    indexingStatus: "ready",
    lastIndexedAt: new Date(Date.now() - 3600000).toISOString(), // 1h ago
    chunkCount: 923,
    languages: ["TypeScript", "CSS", "Rust"],
    fileCount: 156,
    localPath: "/Users/homebase/forge/desktop",
    defaultBranch: "main",
  },
  {
    id: "repo-shared-libs",
    name: "shared-libs",
    source: "https://github.com/middlefingerlabs/shared-libs.git",
    sourceType: "git",
    indexingStatus: "indexing",
    indexingProgress: 67,
    chunkCount: 412,
    languages: ["TypeScript", "JavaScript"],
    fileCount: 89,
    localPath: "/Users/homebase/repos/shared-libs",
    defaultBranch: "main",
  },
];

export const MOCK_FILE_TREE: Record<string, FileNode[]> = {
  "repo-forge-api": [
    {
      name: "src",
      path: "src",
      type: "directory",
      children: [
        {
          name: "routes",
          path: "src/routes",
          type: "directory",
          children: [
            { name: "auth.ts", path: "src/routes/auth.ts", type: "file", language: "TypeScript", chunkCount: 8 },
            { name: "pipelines.ts", path: "src/routes/pipelines.ts", type: "file", language: "TypeScript", chunkCount: 12 },
            { name: "agents.ts", path: "src/routes/agents.ts", type: "file", language: "TypeScript", chunkCount: 6 },
            { name: "users.ts", path: "src/routes/users.ts", type: "file", language: "TypeScript", chunkCount: 5 },
          ],
        },
        {
          name: "models",
          path: "src/models",
          type: "directory",
          children: [
            { name: "User.ts", path: "src/models/User.ts", type: "file", language: "TypeScript", chunkCount: 4 },
            { name: "Pipeline.ts", path: "src/models/Pipeline.ts", type: "file", language: "TypeScript", chunkCount: 7 },
            { name: "Agent.ts", path: "src/models/Agent.ts", type: "file", language: "TypeScript", chunkCount: 3 },
          ],
        },
        {
          name: "middleware",
          path: "src/middleware",
          type: "directory",
          children: [
            { name: "auth.ts", path: "src/middleware/auth.ts", type: "file", language: "TypeScript", chunkCount: 3 },
            { name: "rateLimit.ts", path: "src/middleware/rateLimit.ts", type: "file", language: "TypeScript", chunkCount: 2 },
          ],
        },
        { name: "index.ts", path: "src/index.ts", type: "file", language: "TypeScript", chunkCount: 2 },
        { name: "config.ts", path: "src/config.ts", type: "file", language: "TypeScript", chunkCount: 1 },
      ],
    },
    {
      name: "migrations",
      path: "migrations",
      type: "directory",
      children: [
        { name: "001_users.sql", path: "migrations/001_users.sql", type: "file", language: "SQL", chunkCount: 1 },
        { name: "002_pipelines.sql", path: "migrations/002_pipelines.sql", type: "file", language: "SQL", chunkCount: 1 },
      ],
    },
    { name: "package.json", path: "package.json", type: "file", language: "JSON", chunkCount: 1 },
    { name: "tsconfig.json", path: "tsconfig.json", type: "file", language: "JSON", chunkCount: 1 },
  ],
};
