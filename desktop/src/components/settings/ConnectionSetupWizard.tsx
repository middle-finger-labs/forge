import { useState, useEffect, useCallback } from "react";
import {
  X,
  ArrowLeft,
  ArrowRight,
  Loader2,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Key,
  Shield,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useConnectionStore } from "@/stores/connectionStore";
import { AGENT_REGISTRY, AGENT_ROLES } from "@/types/agent";
import type {
  ServiceType,
  ServicePreset,
  SetupGuide,
  PermissionLevel,
  MCPConnection,
} from "@/types/connection";
import { SERVICE_INFO, PERMISSION_LEVELS } from "@/types/connection";

interface ConnectionSetupWizardProps {
  initialService: ServiceType | null;
  onClose: () => void;
  onComplete: () => void;
}

const STEPS = ["Service", "Authenticate", "Test", "Permissions", "Done"] as const;
type Step = (typeof STEPS)[number];

export function ConnectionSetupWizard({
  initialService,
  onClose,
  onComplete,
}: ConnectionSetupWizardProps) {
  const { serverUrl, authToken } = useConnectionStore();
  const [step, setStep] = useState<Step>(initialService ? "Authenticate" : "Service");
  const [selectedService, setSelectedService] = useState<ServiceType | null>(initialService);
  const [presets, setPresets] = useState<ServicePreset[]>([]);
  const [guide, setGuide] = useState<SetupGuide | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auth state
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [oauthPending, setOauthPending] = useState(false);
  const [oauthDone, setOauthDone] = useState(false);

  // Test state
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "ok" | "error">("idle");
  const [testMessage, setTestMessage] = useState("");

  // Permissions state
  const [defaultPerm, setDefaultPerm] = useState<PermissionLevel>("read");
  const [agentPerms, setAgentPerms] = useState<Record<string, string>>({});

  // Created connection
  const [createdConn, setCreatedConn] = useState<MCPConnection | null>(null);

  const headers = useCallback(
    (): Record<string, string> => ({
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    }),
    [authToken]
  );

  // Fetch presets on mount
  useEffect(() => {
    if (!serverUrl || !authToken) return;
    fetch(`${serverUrl}/api/connections/presets`, { headers: headers() })
      .then((r) => (r.ok ? r.json() : []))
      .then((data: ServicePreset[]) => setPresets(data))
      .catch(() => {});
  }, [serverUrl, authToken, headers]);

  // Fetch setup guide when service is selected
  useEffect(() => {
    if (!selectedService || !serverUrl || !authToken) return;
    setLoading(true);
    fetch(`${serverUrl}/api/connections/setup/${selectedService}`, { headers: headers() })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: SetupGuide | null) => {
        setGuide(data);
        if (data) {
          setDefaultPerm(data.default_permission);
          setAgentPerms({ ...data.agent_permissions });
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedService, serverUrl, authToken, headers]);

  // Listen for OAuth completion
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (
        e.data?.type === "forge:oauth_complete" &&
        e.data?.status === "success"
      ) {
        setOauthDone(true);
        setOauthPending(false);
        if (e.data.connectionId) {
          setCreatedConn({ id: e.data.connectionId } as MCPConnection);
        }
        // Auto-advance to test
        setStep("Test");
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Escape to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Auto-run test when entering Test step
  useEffect(() => {
    if (step !== "Test") return;
    if (testStatus !== "idle") return;
    runTest();
  }, [step]);

  const startOAuth = useCallback(async () => {
    if (!selectedService) return;
    setOauthPending(true);
    setError(null);
    try {
      const res = await fetch(`${serverUrl}/api/connections/oauth/start/${selectedService}`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`OAuth start failed (${res.status})`);
      const data = await res.json();
      // Open OAuth in popup
      window.open(data.authorize_url, "forge_oauth", "width=600,height=700");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start OAuth");
      setOauthPending(false);
    }
  }, [selectedService, serverUrl, headers]);

  const createWithToken = useCallback(async () => {
    if (!selectedService || !guide) return;
    setLoading(true);
    setError(null);
    try {
      // Build credential string from fields
      const credentialValue =
        guide.credential_fields.length === 1
          ? credentials[guide.credential_fields[0].field] ?? ""
          : JSON.stringify(credentials);

      const preset = presets.find((p) => p.service === selectedService);
      const res = await fetch(`${serverUrl}/api/connections`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          service: selectedService,
          display_name: preset?.display_name ?? selectedService,
          credentials: credentialValue,
          default_permission: defaultPerm,
          agent_permissions: agentPerms,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Failed" }));
        throw new Error(body.detail || `Create failed (${res.status})`);
      }
      const conn: MCPConnection = await res.json();
      setCreatedConn(conn);
      setStep("Test");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create connection");
    } finally {
      setLoading(false);
    }
  }, [selectedService, guide, credentials, presets, serverUrl, headers, defaultPerm, agentPerms]);

  const runTest = useCallback(async () => {
    if (!createdConn) {
      setTestStatus("error");
      setTestMessage("No connection created yet");
      return;
    }
    setTestStatus("testing");
    try {
      const res = await fetch(`${serverUrl}/api/connections/${createdConn.id}/test`, {
        method: "POST",
        headers: headers(),
      });
      const data = await res.json();
      setTestStatus(data.status === "ok" ? "ok" : "error");
      setTestMessage(data.message ?? "");
    } catch {
      setTestStatus("error");
      setTestMessage("Connection test failed");
    }
  }, [createdConn, serverUrl, headers]);

  const savePermissions = useCallback(async () => {
    if (!createdConn) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${serverUrl}/api/connections/${createdConn.id}/permissions`,
        {
          method: "PUT",
          headers: headers(),
          body: JSON.stringify({
            default_permission: defaultPerm,
            agent_permissions: agentPerms,
          }),
        }
      );
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      setStep("Done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save permissions");
    } finally {
      setLoading(false);
    }
  }, [createdConn, serverUrl, headers, defaultPerm, agentPerms]);

  const stepIndex = STEPS.indexOf(step);
  const info = selectedService
    ? SERVICE_INFO[selectedService] ?? { emoji: "\u{1F50C}", displayName: selectedService }
    : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-2xl mx-4 bg-[var(--forge-bg)] border border-[var(--forge-border)] rounded-xl shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--forge-border)] shrink-0">
          <div className="flex items-center gap-3">
            {info && <span className="text-xl">{info.emoji}</span>}
            <div>
              <h2 className="text-base font-semibold" style={{ color: "var(--forge-text)" }}>
                {info ? `Connect ${info.displayName}` : "Add Connection"}
              </h2>
              <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                Step {stepIndex + 1} of {STEPS.length}: {step}
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

        {/* Progress bar */}
        <div className="px-6 pt-3 shrink-0">
          <div className="flex gap-1">
            {STEPS.map((s, i) => (
              <div
                key={s}
                className="flex-1 h-1 rounded-full"
                style={{
                  background: i <= stepIndex ? "var(--forge-accent)" : "var(--forge-border)",
                }}
              />
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {error && (
            <div
              className="px-4 py-3 rounded-lg text-sm"
              style={{ background: "rgba(232, 64, 64, 0.1)", color: "var(--forge-error)" }}
            >
              {error}
            </div>
          )}

          {/* Step 1: Select Service */}
          {step === "Service" && (
            <div className="space-y-3">
              <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
                Choose a service to connect to your agent team.
              </p>
              <div className="grid grid-cols-2 gap-2">
                {presets.map((preset) => {
                  const sInfo = SERVICE_INFO[preset.service] ?? {
                    emoji: "\u{1F50C}",
                    displayName: preset.service,
                  };
                  const isSelected = selectedService === preset.service;
                  return (
                    <button
                      key={preset.service}
                      onClick={() => setSelectedService(preset.service)}
                      className="flex items-center gap-3 p-4 rounded-lg text-left transition-colors cursor-pointer"
                      style={{
                        background: isSelected ? "var(--forge-accent)" : "var(--forge-channel)",
                        color: isSelected ? "#fff" : "var(--forge-text)",
                        border: `1px solid ${
                          isSelected ? "var(--forge-accent)" : "var(--forge-border)"
                        }`,
                      }}
                    >
                      <span className="text-2xl">{sInfo.emoji}</span>
                      <div>
                        <div className="text-sm font-medium">{sInfo.displayName}</div>
                        <div
                          className="text-xs mt-0.5"
                          style={{
                            color: isSelected ? "rgba(255,255,255,0.7)" : "var(--forge-text-muted)",
                          }}
                        >
                          {preset.auth_type === "oauth" ? "OAuth" : "API Token"}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Step 2: Authenticate */}
          {step === "Authenticate" && guide && (
            <div className="space-y-4">
              {guide.setup_instructions && (
                <div
                  className="px-4 py-3 rounded-lg text-xs leading-relaxed"
                  style={{
                    background: "var(--forge-channel)",
                    color: "var(--forge-text-muted)",
                    border: "1px solid var(--forge-border)",
                  }}
                >
                  {guide.setup_instructions}
                </div>
              )}

              {/* OAuth button */}
              {guide.oauth_available && (
                <div className="space-y-3">
                  <button
                    onClick={startOAuth}
                    disabled={oauthPending || oauthDone}
                    className={cn(
                      "w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg text-sm font-medium transition-colors cursor-pointer",
                      oauthDone
                        ? "bg-[var(--forge-success)]/20 text-[var(--forge-success)]"
                        : "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)]"
                    )}
                  >
                    {oauthPending ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Waiting for authorization...
                      </>
                    ) : oauthDone ? (
                      <>
                        <CheckCircle2 className="w-4 h-4" />
                        Connected via OAuth
                      </>
                    ) : (
                      <>
                        <ExternalLink className="w-4 h-4" />
                        Connect with {info?.displayName ?? "OAuth"}
                      </>
                    )}
                  </button>
                  {!oauthDone && guide.credential_fields.length > 0 && (
                    <div className="flex items-center gap-3">
                      <div className="flex-1 h-px" style={{ background: "var(--forge-border)" }} />
                      <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                        or use a token
                      </span>
                      <div className="flex-1 h-px" style={{ background: "var(--forge-border)" }} />
                    </div>
                  )}
                </div>
              )}

              {/* Token fields */}
              {!oauthDone &&
                guide.credential_fields.map((field) => (
                  <div key={field.field}>
                    <label
                      className="flex items-center gap-1.5 text-xs font-medium mb-1.5"
                      style={{ color: "var(--forge-text-muted)" }}
                    >
                      <Key className="w-3 h-3" />
                      {field.label}
                    </label>
                    <input
                      value={credentials[field.field] ?? ""}
                      onChange={(e) =>
                        setCredentials((prev) => ({ ...prev, [field.field]: e.target.value }))
                      }
                      placeholder={field.placeholder}
                      type={field.field === "token" ? "password" : "text"}
                      className={cn(
                        "w-full px-3 py-2 rounded-lg text-sm",
                        "bg-[var(--forge-channel)] border border-[var(--forge-border)]",
                        "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                        "outline-none focus:border-[var(--forge-accent)] transition-colors"
                      )}
                    />
                    <p className="text-[10px] mt-1" style={{ color: "var(--forge-text-muted)" }}>
                      {field.help}
                    </p>
                  </div>
                ))}
            </div>
          )}

          {step === "Authenticate" && !guide && loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2
                className="w-5 h-5 animate-spin"
                style={{ color: "var(--forge-text-muted)" }}
              />
            </div>
          )}

          {/* Step 3: Test */}
          {step === "Test" && (
            <div className="flex flex-col items-center justify-center py-8 space-y-4">
              {testStatus === "testing" && (
                <>
                  <Loader2
                    className="w-10 h-10 animate-spin"
                    style={{ color: "var(--forge-accent)" }}
                  />
                  <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
                    Testing connection...
                  </p>
                </>
              )}
              {testStatus === "ok" && (
                <>
                  <CheckCircle2 className="w-10 h-10" style={{ color: "var(--forge-success)" }} />
                  <p className="text-sm font-medium" style={{ color: "var(--forge-success)" }}>
                    Connection successful!
                  </p>
                  <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                    {testMessage}
                  </p>
                </>
              )}
              {testStatus === "error" && (
                <>
                  <XCircle className="w-10 h-10" style={{ color: "var(--forge-error)" }} />
                  <p className="text-sm font-medium" style={{ color: "var(--forge-error)" }}>
                    Connection failed
                  </p>
                  <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                    {testMessage}
                  </p>
                  <button
                    onClick={() => {
                      setTestStatus("idle");
                      runTest();
                    }}
                    className="text-xs cursor-pointer transition-colors"
                    style={{ color: "var(--forge-accent)" }}
                  >
                    Retry
                  </button>
                </>
              )}
            </div>
          )}

          {/* Step 4: Permissions */}
          {step === "Permissions" && (
            <div className="space-y-4">
              <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
                Configure which agents can access {info?.displayName} and at what level.
              </p>

              {/* Default */}
              <div>
                <label
                  className="block text-xs font-medium uppercase tracking-wider mb-2"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  Default Permission
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

              {/* Per-agent */}
              <div>
                <label
                  className="block text-xs font-medium uppercase tracking-wider mb-2"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  Per-Agent Overrides
                </label>
                <div
                  className="rounded-lg overflow-hidden"
                  style={{ border: "1px solid var(--forge-border)" }}
                >
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
                        <select
                          value={perm}
                          onChange={(e) =>
                            setAgentPerms((prev) => ({ ...prev, [role]: e.target.value }))
                          }
                          className="px-2 py-1 rounded text-xs outline-none cursor-pointer"
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
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Step 5: Done */}
          {step === "Done" && (
            <div className="flex flex-col items-center justify-center py-8 space-y-4">
              <div className="w-14 h-14 rounded-full flex items-center justify-center bg-[var(--forge-success)]/20">
                <Check className="w-7 h-7" style={{ color: "var(--forge-success)" }} />
              </div>
              <h3 className="text-base font-semibold" style={{ color: "var(--forge-text)" }}>
                {info?.displayName} Connected!
              </h3>
              <div
                className="w-full max-w-sm rounded-lg p-4 space-y-2"
                style={{
                  background: "var(--forge-channel)",
                  border: "1px solid var(--forge-border)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                  Your agents can now:
                </div>
                {AGENT_ROLES.filter((role) => {
                  const perm = agentPerms[role] ?? defaultPerm;
                  return perm !== "none";
                }).map((role) => {
                  const agent = AGENT_REGISTRY[role];
                  const perm = agentPerms[role] ?? defaultPerm;
                  return (
                    <div key={role} className="flex items-center gap-2 text-xs">
                      <span>{agent.emoji}</span>
                      <span style={{ color: "var(--forge-text)" }}>{agent.displayName}</span>
                      <span style={{ color: "var(--forge-text-muted)" }}>
                        &mdash; {perm} access
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--forge-border)] shrink-0">
          <div>
            {stepIndex > 0 && step !== "Done" && (
              <button
                onClick={() => setStep(STEPS[stepIndex - 1])}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                style={{ color: "var(--forge-text-muted)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--forge-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <ArrowLeft className="w-3 h-3" />
                Back
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {step === "Done" ? (
              <button
                onClick={onComplete}
                className={cn(
                  "flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg transition-colors cursor-pointer",
                  "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)]"
                )}
              >
                <Check className="w-3.5 h-3.5" />
                Done
              </button>
            ) : step === "Service" ? (
              <button
                onClick={() => {
                  if (selectedService) setStep("Authenticate");
                }}
                disabled={!selectedService}
                className={cn(
                  "flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg transition-colors",
                  selectedService
                    ? "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)] cursor-pointer"
                    : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] cursor-not-allowed"
                )}
              >
                Next
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            ) : step === "Authenticate" ? (
              <>
                {oauthDone ? (
                  <button
                    onClick={() => setStep("Test")}
                    className="flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)] cursor-pointer transition-colors"
                  >
                    Next
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={createWithToken}
                    disabled={
                      loading ||
                      (!guide?.credential_fields.some((f) => credentials[f.field]?.trim()))
                    }
                    className={cn(
                      "flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg transition-colors",
                      !loading &&
                        guide?.credential_fields.some((f) => credentials[f.field]?.trim())
                        ? "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)] cursor-pointer"
                        : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] cursor-not-allowed"
                    )}
                  >
                    {loading ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Key className="w-3.5 h-3.5" />
                    )}
                    Connect with Token
                  </button>
                )}
              </>
            ) : step === "Test" ? (
              <button
                onClick={() => setStep("Permissions")}
                disabled={testStatus === "testing"}
                className={cn(
                  "flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg transition-colors",
                  testStatus !== "testing"
                    ? "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)] cursor-pointer"
                    : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] cursor-not-allowed"
                )}
              >
                {testStatus === "ok" ? "Configure Permissions" : "Skip"}
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            ) : step === "Permissions" ? (
              <button
                onClick={savePermissions}
                disabled={loading}
                className="flex items-center gap-1.5 px-5 py-2 text-xs font-medium rounded-lg bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)] cursor-pointer transition-colors"
              >
                {loading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Shield className="w-3.5 h-3.5" />
                )}
                Save & Finish
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
