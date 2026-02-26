import { useState, useEffect, useCallback } from "react";
import {
  X,
  Save,
  Loader2,
  CheckCircle2,
  XCircle,
  Wrench,
  Shield,
  Search,
  ToggleLeft,
  ToggleRight,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMCPConnectionStore } from "@/stores/mcpConnectionStore";
import { AGENT_REGISTRY, AGENT_ROLES } from "@/types/agent";
import type {
  MCPConnection,
  ToolWithPermission,
  PermissionLevel,
  AutomationConfig,
} from "@/types/connection";
import { SERVICE_INFO, PERMISSION_LEVELS, DEFAULT_AUTOMATION, AUTOMATION_LABELS } from "@/types/connection";

interface ConnectionConfigModalProps {
  connectionId: string;
  onClose: () => void;
  onSaved: () => void;
}

type TabId = "permissions" | "tools" | "automation";

export function ConnectionConfigModal({
  connectionId,
  onClose,
  onSaved,
}: ConnectionConfigModalProps) {
  const store = useMCPConnectionStore();
  const [conn, setConn] = useState<MCPConnection | null>(null);
  const [tools, setTools] = useState<ToolWithPermission[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("permissions");
  const [toolSearch, setToolSearch] = useState("");

  // Editable state
  const [defaultPerm, setDefaultPerm] = useState<PermissionLevel>("read");
  const [agentPerms, setAgentPerms] = useState<Record<string, string>>({});
  const [toolToggles, setToolToggles] = useState<Record<string, boolean>>({});
  const [automationFlags, setAutomationFlags] = useState<AutomationConfig>({ ...DEFAULT_AUTOMATION });

  // Fetch connection + tools
  useEffect(() => {
    setLoading(true);
    Promise.all([
      store.getConnection(connectionId),
      store.getConnectionTools(connectionId),
    ])
      .then(([connData, toolData]: [MCPConnection, ToolWithPermission[]]) => {
        setConn(connData);
        setTools(toolData);
        setDefaultPerm(connData.default_permission);
        setAgentPerms({ ...connData.agent_permissions });
        setAutomationFlags({ ...DEFAULT_AUTOMATION, ...connData.automation_config });
        const toggles: Record<string, boolean> = {};
        for (const t of toolData) {
          toggles[t.name] = t.allowed;
        }
        setToolToggles(toggles);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [connectionId, store]);

  // Escape to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const data = await store.testConnection(connectionId);
      setTestResult({ status: data.status, message: data.message ?? "" });
    } catch {
      setTestResult({ status: "error", message: "Request failed" });
    } finally {
      setTesting(false);
    }
  }, [connectionId, store]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await store.updatePermissions(connectionId, {
        default_permission: defaultPerm,
        agent_permissions: agentPerms,
        tool_permissions: Object.entries(toolToggles).map(([name, allowed]) => ({
          tool_name: name,
          allowed,
        })),
      });
      await store.updateAutomation(connectionId, automationFlags);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }, [connectionId, store, defaultPerm, agentPerms, toolToggles, automationFlags, onSaved, onClose]);

  if (loading || !conn) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
        <div className="relative flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin" style={{ color: "var(--forge-text-muted)" }} />
        </div>
      </div>
    );
  }

  const info = SERVICE_INFO[conn.service] ?? { emoji: "\u{1F50C}", displayName: conn.service };

  // Group tools by classification
  const filteredTools = tools.filter(
    (t) =>
      !toolSearch ||
      t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      t.description.toLowerCase().includes(toolSearch.toLowerCase())
  );
  const readTools = filteredTools.filter((t) => t.classification === "read");
  const writeTools = filteredTools.filter((t) => t.classification === "write");
  const adminTools = filteredTools.filter((t) => t.classification === "admin");

  const toggleGroup = (classification: string, enabled: boolean) => {
    setToolToggles((prev) => {
      const next = { ...prev };
      for (const t of tools) {
        if (t.classification === classification) {
          next[t.name] = enabled;
        }
      }
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-2xl mx-4 bg-[var(--forge-bg)] border border-[var(--forge-border)] rounded-xl shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--forge-border)] shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-xl">{info.emoji}</span>
            <div>
              <h2 className="text-base font-semibold" style={{ color: "var(--forge-text)" }}>
                {conn.display_name}
              </h2>
              <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                {info.displayName} &middot; {conn.tool_count} tools
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg transition-colors cursor-pointer"
            style={{ color: "var(--forge-text-muted)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--forge-hover)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab bar */}
        <div
          className="flex gap-1 px-6 py-2 shrink-0"
          style={{ borderBottom: "1px solid var(--forge-border)" }}
        >
          {(
            [
              { id: "permissions" as TabId, label: "Permissions", icon: Shield },
              { id: "tools" as TabId, label: "Tools", icon: Wrench },
              { id: "automation" as TabId, label: "Automation", icon: Zap },
            ] as const
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
              style={{
                background: tab === id ? "var(--forge-hover)" : "transparent",
                color: tab === id ? "var(--forge-text)" : "var(--forge-text-muted)",
              }}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
          {error && (
            <div
              className="px-4 py-3 rounded-lg text-sm"
              style={{ background: "rgba(232, 64, 64, 0.1)", color: "var(--forge-error)" }}
            >
              {error}
            </div>
          )}

          {tab === "permissions" && (
            <>
              {/* Default permission */}
              <div>
                <label
                  className="block text-xs font-medium uppercase tracking-wider mb-2"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  Default Permission Level
                </label>
                <div className="flex gap-1">
                  {PERMISSION_LEVELS.map((level) => (
                    <button
                      key={level}
                      onClick={() => setDefaultPerm(level)}
                      className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background:
                          defaultPerm === level ? "var(--forge-accent)" : "var(--forge-channel)",
                        color: defaultPerm === level ? "#fff" : "var(--forge-text-muted)",
                        border: `1px solid ${
                          defaultPerm === level ? "var(--forge-accent)" : "var(--forge-border)"
                        }`,
                      }}
                    >
                      {level.charAt(0).toUpperCase() + level.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Per-agent permissions */}
              <div>
                <label
                  className="block text-xs font-medium uppercase tracking-wider mb-2"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  Agent Permission Overrides
                </label>
                <div
                  className="rounded-lg overflow-hidden"
                  style={{ border: "1px solid var(--forge-border)" }}
                >
                  {/* Table header */}
                  <div
                    className="flex items-center px-4 py-2 text-xs font-medium"
                    style={{
                      background: "var(--forge-hover)",
                      color: "var(--forge-text-muted)",
                    }}
                  >
                    <div className="flex-1">Agent</div>
                    <div className="w-32">Permission</div>
                  </div>
                  {AGENT_ROLES.map((role, i) => {
                    const agent = AGENT_REGISTRY[role];
                    const perm = agentPerms[role] ?? defaultPerm;
                    return (
                      <div
                        key={role}
                        className="flex items-center px-4 py-2"
                        style={{
                          background: "var(--forge-channel)",
                          borderTop: i > 0 ? "1px solid var(--forge-border)" : undefined,
                        }}
                      >
                        <div className="flex-1 flex items-center gap-2">
                          <span>{agent.emoji}</span>
                          <span className="text-sm" style={{ color: "var(--forge-text)" }}>
                            {agent.displayName}
                          </span>
                        </div>
                        <div className="w-32">
                          <select
                            value={perm}
                            onChange={(e) =>
                              setAgentPerms((prev) => ({
                                ...prev,
                                [role]: e.target.value,
                              }))
                            }
                            className="w-full px-2 py-1 rounded text-xs outline-none cursor-pointer"
                            style={{
                              background: "var(--forge-bg)",
                              color: "var(--forge-text)",
                              border: "1px solid var(--forge-border)",
                            }}
                          >
                            {PERMISSION_LEVELS.map((l) => (
                              <option key={l} value={l}>
                                {l.charAt(0).toUpperCase() + l.slice(1)}
                                {l === defaultPerm ? " (default)" : ""}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {tab === "automation" && (
            <>
              <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                Control what happens automatically when pipelines run with this connection.
              </p>
              <div
                className="rounded-lg overflow-hidden"
                style={{ border: "1px solid var(--forge-border)" }}
              >
                {(Object.keys(AUTOMATION_LABELS) as Array<keyof AutomationConfig>).map((key, i) => {
                  const { label, description } = AUTOMATION_LABELS[key];
                  const enabled = automationFlags[key];
                  return (
                    <div
                      key={key}
                      className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                      style={{
                        background: "var(--forge-channel)",
                        borderTop: i > 0 ? "1px solid var(--forge-border)" : undefined,
                      }}
                      onClick={() =>
                        setAutomationFlags((prev) => ({ ...prev, [key]: !prev[key] }))
                      }
                    >
                      {enabled ? (
                        <ToggleRight className="w-5 h-5 shrink-0" style={{ color: "var(--forge-accent)" }} />
                      ) : (
                        <ToggleLeft className="w-5 h-5 shrink-0" style={{ color: "var(--forge-text-muted)" }} />
                      )}
                      <div className="flex-1 min-w-0">
                        <div
                          className="text-sm font-medium"
                          style={{ color: enabled ? "var(--forge-text)" : "var(--forge-text-muted)" }}
                        >
                          {label}
                        </div>
                        <div className="text-xs mt-0.5" style={{ color: "var(--forge-text-muted)" }}>
                          {description}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {tab === "tools" && (
            <>
              {/* Search */}
              <div className="relative">
                <Search
                  className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
                  style={{ color: "var(--forge-text-muted)" }}
                />
                <input
                  value={toolSearch}
                  onChange={(e) => setToolSearch(e.target.value)}
                  placeholder="Filter tools..."
                  className="w-full pl-9 pr-3 py-2 rounded-lg text-sm outline-none"
                  style={{
                    background: "var(--forge-channel)",
                    color: "var(--forge-text)",
                    border: "1px solid var(--forge-border)",
                  }}
                />
              </div>

              {tools.length === 0 ? (
                <div
                  className="text-center py-8 rounded-lg"
                  style={{
                    background: "var(--forge-channel)",
                    border: "1px solid var(--forge-border)",
                  }}
                >
                  <Wrench
                    className="w-8 h-8 mx-auto mb-2"
                    style={{ color: "var(--forge-text-muted)" }}
                  />
                  <div className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
                    No tools discovered yet
                  </div>
                  <div className="text-xs mt-1" style={{ color: "var(--forge-text-muted)" }}>
                    Test the connection to discover available tools
                  </div>
                </div>
              ) : (
                <>
                  {[
                    { label: "Read Tools", items: readTools, cls: "read" },
                    { label: "Write Tools", items: writeTools, cls: "write" },
                    { label: "Admin Tools", items: adminTools, cls: "admin" },
                  ]
                    .filter((g) => g.items.length > 0)
                    .map((group) => (
                      <ToolGroup
                        key={group.cls}
                        label={group.label}
                        classification={group.cls}
                        items={group.items}
                        toggles={toolToggles}
                        onToggle={(name) =>
                          setToolToggles((prev) => ({ ...prev, [name]: !prev[name] }))
                        }
                        onToggleAll={(enabled) => toggleGroup(group.cls, enabled)}
                      />
                    ))}
                </>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between px-6 py-4 border-t border-[var(--forge-border)] shrink-0"
        >
          <div className="flex items-center gap-2">
            <button
              onClick={handleTest}
              disabled={testing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
              style={{
                background: "var(--forge-hover)",
                color: "var(--forge-text)",
              }}
            >
              {testing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Zap className="w-3.5 h-3.5" />
              )}
              Test Connection
            </button>
            {testResult && (
              <span
                className="flex items-center gap-1 text-xs"
                style={{
                  color:
                    testResult.status === "ok"
                      ? "var(--forge-success)"
                      : "var(--forge-error)",
                }}
              >
                {testResult.status === "ok" ? (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                ) : (
                  <XCircle className="w-3.5 h-3.5" />
                )}
                {testResult.message}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium rounded-lg transition-colors cursor-pointer"
              style={{ color: "var(--forge-text-muted)" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--forge-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className={cn(
                "flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg transition-colors cursor-pointer",
                "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)]"
              )}
            >
              {saving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Tool Group Sub-component ────────────────────────

function ToolGroup({
  label,
  classification,
  items,
  toggles,
  onToggle,
  onToggleAll,
}: {
  label: string;
  classification: string;
  items: ToolWithPermission[];
  toggles: Record<string, boolean>;
  onToggle: (name: string) => void;
  onToggleAll: (enabled: boolean) => void;
}) {
  const allEnabled = items.every((t) => toggles[t.name] !== false);
  const colorMap: Record<string, string> = {
    read: "var(--forge-success)",
    write: "var(--forge-warning)",
    admin: "var(--forge-error)",
  };
  const color = colorMap[classification] ?? "var(--forge-text-muted)";

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ background: color }}
          />
          <span className="text-xs font-medium" style={{ color: "var(--forge-text)" }}>
            {label}
          </span>
          <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
            ({items.length})
          </span>
        </div>
        <button
          onClick={() => onToggleAll(!allEnabled)}
          className="text-xs cursor-pointer transition-colors"
          style={{ color: "var(--forge-accent)" }}
        >
          {allEnabled ? "Disable all" : "Enable all"}
        </button>
      </div>
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: "1px solid var(--forge-border)" }}
      >
        {items.map((tool, i) => {
          const enabled = toggles[tool.name] !== false;
          return (
            <div
              key={tool.name}
              className="flex items-center gap-3 px-4 py-2 cursor-pointer"
              style={{
                background: "var(--forge-channel)",
                borderTop: i > 0 ? "1px solid var(--forge-border)" : undefined,
                opacity: enabled ? 1 : 0.5,
              }}
              onClick={() => onToggle(tool.name)}
            >
              {enabled ? (
                <ToggleRight className="w-4 h-4 shrink-0" style={{ color: "var(--forge-accent)" }} />
              ) : (
                <ToggleLeft className="w-4 h-4 shrink-0" style={{ color: "var(--forge-text-muted)" }} />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-xs font-mono" style={{ color: "var(--forge-text)" }}>
                  {tool.name}
                </div>
                {tool.description && (
                  <div
                    className="text-xs truncate mt-0.5"
                    style={{ color: "var(--forge-text-muted)" }}
                  >
                    {tool.description}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
