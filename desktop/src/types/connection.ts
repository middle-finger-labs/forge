export type ServiceType = "notion" | "linear" | "figma" | "jira" | "google_drive";
export type PermissionLevel = "none" | "read" | "write" | "full";
export type TransportType = "stdio" | "sse" | "streamable_http";

export interface MCPConnection {
  id: string;
  org_id: string;
  service: ServiceType;
  display_name: string;
  transport: TransportType;
  server_url?: string;
  command?: string;
  args: string[];
  auth_type: string;
  has_credentials: boolean;
  default_permission: PermissionLevel;
  agent_permissions: Record<string, string>;
  tool_permissions: ToolPermissionEntry[];
  automation_config: Partial<AutomationConfig>;
  enabled: boolean;
  last_connected_at?: string;
  discovered_tools: DiscoveredTool[];
  tool_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface ToolPermissionEntry {
  tool_name: string;
  allowed: boolean;
  allowed_agents?: string[];
}

export interface DiscoveredTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface ServicePreset {
  service: ServiceType;
  display_name: string;
  transport: TransportType;
  server_url?: string;
  command?: string;
  args?: string[];
  auth_type: string;
  default_permission: PermissionLevel;
  agent_permissions: Record<string, string>;
  oauth_available: boolean;
  setup_instructions: string;
}

export interface TestConnectionResult {
  status: "ok" | "error";
  tools: DiscoveredTool[];
  tool_count: number;
  message?: string;
}

export interface SetupGuide {
  service: ServiceType;
  display_name: string;
  auth_type: string;
  transport: TransportType;
  default_permission: PermissionLevel;
  agent_permissions: Record<string, string>;
  oauth_available: boolean;
  setup_instructions: string;
  credential_fields: CredentialField[];
}

export interface CredentialField {
  field: string;
  label: string;
  placeholder: string;
  help: string;
}

export interface OAuthStartResult {
  authorize_url: string;
  state: string;
}

export interface ToolWithPermission {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  classification: "read" | "write" | "admin";
  allowed: boolean;
  allowed_agents?: string[];
}

export const SERVICE_INFO: Record<ServiceType, { emoji: string; displayName: string }> = {
  notion:       { emoji: "\u{1F4D3}", displayName: "Notion" },
  linear:       { emoji: "\u{1F537}", displayName: "Linear" },
  figma:        { emoji: "\u{1F3A8}", displayName: "Figma" },
  jira:         { emoji: "\u{1F3AB}", displayName: "Jira" },
  google_drive: { emoji: "\u{1F4C4}", displayName: "Google Drive" },
};

export const PERMISSION_LEVELS: PermissionLevel[] = ["none", "read", "write", "full"];

// Automation config types
export interface AutomationConfig {
  auto_search_context: boolean;
  auto_create_spec_page: boolean;
  auto_create_tickets: boolean;
  auto_update_tickets: boolean;
  auto_create_bug_tickets: boolean;
}

export const DEFAULT_AUTOMATION: AutomationConfig = {
  auto_search_context: true,
  auto_create_spec_page: true,
  auto_create_tickets: true,
  auto_update_tickets: true,
  auto_create_bug_tickets: true,
};

export const AUTOMATION_LABELS: Record<keyof AutomationConfig, { label: string; description: string }> = {
  auto_search_context:    { label: "Search for context",     description: "Search connected services for related docs and tickets when a pipeline starts" },
  auto_create_spec_page:  { label: "Create spec pages",      description: "Create a Notion page with the product spec after business analysis" },
  auto_create_tickets:    { label: "Create tickets",          description: "Create Linear/Jira tickets from the PM's task breakdown" },
  auto_update_tickets:    { label: "Update ticket status",    description: "Mark tickets as Done when a pipeline completes successfully" },
  auto_create_bug_tickets:{ label: "Create bug tickets",      description: "Create bug tickets for critical QA findings and pipeline failures" },
};

// Tool call audit log entry
export interface ConnectionToolCall {
  id: string;
  connection_id: string;
  service: ServiceType;
  display_name: string;
  pipeline_id?: string;
  agent_role?: string;
  tool_name: string;
  arguments?: Record<string, unknown>;
  result_summary?: string;
  success: boolean;
  duration_ms?: number;
  error_message?: string;
  created_at: string;
}
