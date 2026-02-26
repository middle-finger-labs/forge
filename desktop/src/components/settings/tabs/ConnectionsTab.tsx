import { useState, useEffect, useCallback } from "react";
import {
  Plug,
  Plus,
  Settings2,
  Unplug,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { useMCPConnectionStore } from "@/stores/mcpConnectionStore";
import { Section } from "./GeneralTab";
import { ConnectionConfigModal } from "../ConnectionConfigModal";
import { ConnectionSetupWizard } from "../ConnectionSetupWizard";
import type { ServiceType } from "@/types/connection";
import { SERVICE_INFO } from "@/types/connection";
import type { MCPConnection } from "@/types/connection";

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function permissionSummary(conn: MCPConnection): string {
  const parts = [`Default: ${capitalize(conn.default_permission)}`];
  for (const [agent, perm] of Object.entries(conn.agent_permissions)) {
    if (perm !== conn.default_permission) {
      parts.push(`${agent.toUpperCase()}: ${capitalize(perm)}`);
    }
  }
  return parts.slice(0, 4).join(" \u00b7 ");
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function ConnectionsTab() {
  const { connections, presets, loading, error, fetchAll, deleteConnection } =
    useMCPConnectionStore();

  // Modal / wizard state
  const [configId, setConfigId] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardService, setWizardService] = useState<ServiceType | null>(null);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleDisconnect = useCallback(
    async (id: string) => {
      try {
        await deleteConnection(id);
      } catch {
        /* best effort */
      }
    },
    [deleteConnection]
  );

  // Listen for OAuth completion
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "forge:oauth_complete" && e.data?.status === "success") {
        fetchAll();
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [fetchAll]);

  // Split presets into connected vs available
  const connectedServices = new Set(connections.map((c) => c.service));
  const availablePresets = presets.filter((p) => !connectedServices.has(p.service));

  if (loading) {
    return (
      <div className="max-w-2xl flex items-center justify-center py-16">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--forge-text-muted)" }} />
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-8">
      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm"
          style={{ background: "rgba(232, 64, 64, 0.1)", color: "var(--forge-error)" }}
        >
          {error}
        </div>
      )}

      {/* Connected services */}
      <Section title="Connected">
        {connections.length === 0 ? (
          <div
            className="text-center py-8 rounded-lg"
            style={{
              background: "var(--forge-channel)",
              border: "1px solid var(--forge-border)",
            }}
          >
            <Plug
              className="w-8 h-8 mx-auto mb-2"
              style={{ color: "var(--forge-text-muted)" }}
            />
            <div className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
              No connections yet
            </div>
            <div className="text-xs mt-1" style={{ color: "var(--forge-text-muted)" }}>
              Connect a service below to give your agents external tools
            </div>
          </div>
        ) : (
          <div
            className="rounded-lg overflow-hidden"
            style={{ border: "1px solid var(--forge-border)" }}
          >
            {connections.map((conn, i) => {
              const info = SERVICE_INFO[conn.service] ?? { emoji: "\u{1F50C}", displayName: conn.service };
              return (
                <div
                  key={conn.id}
                  className="px-4 py-3"
                  style={{
                    background: "var(--forge-channel)",
                    borderTop: i > 0 ? "1px solid var(--forge-border)" : undefined,
                  }}
                >
                  {/* Top row: icon, name, status */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span className="text-lg">{info.emoji}</span>
                      <div>
                        <span className="text-sm font-medium" style={{ color: "var(--forge-text)" }}>
                          {info.displayName}
                        </span>
                        <span className="text-sm ml-1.5" style={{ color: "var(--forge-text-muted)" }}>
                          &mdash; {conn.display_name}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {conn.has_credentials ? (
                        <span className="flex items-center gap-1 text-xs" style={{ color: "var(--forge-success)" }}>
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Connected
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-xs" style={{ color: "var(--forge-warning)" }}>
                          <XCircle className="w-3.5 h-3.5" />
                          No credentials
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Details row */}
                  <div className="mt-1.5 ml-8 text-xs" style={{ color: "var(--forge-text-muted)" }}>
                    <span>{conn.tool_count} tool{conn.tool_count !== 1 ? "s" : ""} available</span>
                    {conn.last_connected_at && (
                      <span> &middot; Last used {timeAgo(conn.last_connected_at)}</span>
                    )}
                  </div>

                  {/* Permissions summary */}
                  <div className="mt-1 ml-8 text-xs" style={{ color: "var(--forge-text-muted)" }}>
                    {permissionSummary(conn)}
                  </div>

                  {/* Actions */}
                  <div className="mt-2.5 ml-8 flex items-center gap-2">
                    <button
                      onClick={() => setConfigId(conn.id)}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: "var(--forge-hover)",
                        color: "var(--forge-text)",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--forge-border)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "var(--forge-hover)")}
                    >
                      <Settings2 className="w-3 h-3" />
                      Configure
                    </button>
                    <button
                      onClick={() => handleDisconnect(conn.id)}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: "transparent",
                        color: "var(--forge-text-muted)",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.color = "var(--forge-error)";
                        e.currentTarget.style.background = "rgba(232, 64, 64, 0.1)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.color = "var(--forge-text-muted)";
                        e.currentTarget.style.background = "transparent";
                      }}
                    >
                      <Unplug className="w-3 h-3" />
                      Disconnect
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* Available services */}
      {availablePresets.length > 0 && (
        <Section title="Available">
          <div
            className="rounded-lg overflow-hidden"
            style={{ border: "1px solid var(--forge-border)" }}
          >
            {availablePresets.map((preset, i) => {
              const info = SERVICE_INFO[preset.service] ?? { emoji: "\u{1F50C}", displayName: preset.service };
              return (
                <div
                  key={preset.service}
                  className="flex items-center justify-between px-4 py-3"
                  style={{
                    background: "var(--forge-channel)",
                    borderTop: i > 0 ? "1px solid var(--forge-border)" : undefined,
                  }}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg">{info.emoji}</span>
                    <div>
                      <div className="text-sm font-medium" style={{ color: "var(--forge-text)" }}>
                        {info.displayName}
                      </div>
                      <div className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                        {preset.auth_type === "oauth" ? "OAuth" : "API Token"} &middot;{" "}
                        {capitalize(preset.transport.replace("_", " "))}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      setWizardService(preset.service);
                      setWizardOpen(true);
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition-colors"
                    style={{
                      background: "var(--forge-accent)",
                      color: "#fff",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--forge-active)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "var(--forge-accent)")}
                  >
                    <Plus className="w-3 h-3" />
                    Connect
                  </button>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Refresh */}
      <div className="flex justify-end">
        <button
          onClick={fetchAll}
          className="flex items-center gap-1.5 text-xs cursor-pointer transition-colors"
          style={{ color: "var(--forge-text-muted)" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-text)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
        >
          <RefreshCw className="w-3 h-3" />
          Refresh
        </button>
      </div>

      {/* Modals */}
      {configId && (
        <ConnectionConfigModal
          connectionId={configId}
          onClose={() => setConfigId(null)}
          onSaved={fetchAll}
        />
      )}

      {wizardOpen && (
        <ConnectionSetupWizard
          initialService={wizardService}
          onClose={() => {
            setWizardOpen(false);
            setWizardService(null);
          }}
          onComplete={() => {
            setWizardOpen(false);
            setWizardService(null);
            fetchAll();
          }}
        />
      )}
    </div>
  );
}
