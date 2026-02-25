import { useSettingsStore, type AgentSettings } from "@/stores/settingsStore";
import { AGENT_REGISTRY, AGENT_ROLES, type AgentRole } from "@/types/agent";
import { Section } from "./GeneralTab";

const MODEL_OPTIONS = [
  { value: "auto", label: "Auto (server default)" },
  { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o mini" },
];

const VERBOSITY_OPTIONS = [
  { value: "concise", label: "Concise" },
  { value: "normal", label: "Normal" },
  { value: "verbose", label: "Verbose" },
];

export function AgentsTab() {
  const { agentSettings, setAgentSettings } = useSettingsStore();

  return (
    <div className="max-w-lg space-y-6">
      <Section title="Agent Configuration">
        <p className="text-xs mb-4" style={{ color: "var(--forge-text-muted)" }}>
          Customize how each agent behaves. These settings are synced with your
          Forge server.
        </p>
      </Section>

      {AGENT_ROLES.map((role) => (
        <AgentCard
          key={role}
          role={role}
          settings={agentSettings[role] ?? {}}
          onChange={(s) => setAgentSettings(role, s)}
        />
      ))}
    </div>
  );
}

function AgentCard({
  role,
  settings,
  onChange,
}: {
  role: AgentRole;
  settings: AgentSettings;
  onChange: (s: AgentSettings) => void;
}) {
  const info = AGENT_REGISTRY[role];

  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: "var(--forge-channel)",
        border: "1px solid var(--forge-border)",
      }}
    >
      {/* Agent header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">{info.emoji}</span>
        <span className="text-sm font-medium" style={{ color: "var(--forge-text)" }}>
          {info.displayName}
        </span>
      </div>

      <div className="space-y-3">
        {/* Model */}
        <div className="flex items-center justify-between">
          <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
            Model
          </span>
          <select
            value={settings.model ?? "auto"}
            onChange={(e) =>
              onChange({
                ...settings,
                model: e.target.value === "auto" ? undefined : e.target.value,
              })
            }
            className="px-2 py-1 rounded-md text-xs cursor-pointer outline-none"
            style={{
              background: "var(--forge-bg)",
              color: "var(--forge-text)",
              border: "1px solid var(--forge-border)",
            }}
          >
            {MODEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Verbosity */}
        <div className="flex items-center justify-between">
          <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
            Verbosity
          </span>
          <div className="flex gap-1">
            {VERBOSITY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() =>
                  onChange({
                    ...settings,
                    verbosity: opt.value as AgentSettings["verbosity"],
                  })
                }
                className="px-2 py-1 rounded text-xs transition-colors cursor-pointer"
                style={{
                  background:
                    (settings.verbosity ?? "normal") === opt.value
                      ? "var(--forge-accent)"
                      : "var(--forge-bg)",
                  color:
                    (settings.verbosity ?? "normal") === opt.value
                      ? "#fff"
                      : "var(--forge-text-muted)",
                  border: `1px solid ${
                    (settings.verbosity ?? "normal") === opt.value
                      ? "var(--forge-accent)"
                      : "var(--forge-border)"
                  }`,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Auto-approve */}
        <div className="flex items-center justify-between">
          <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
            Auto-approve actions
          </span>
          <button
            onClick={() =>
              onChange({ ...settings, autoApprove: !settings.autoApprove })
            }
            className="relative w-9 h-[18px] rounded-full shrink-0 transition-colors cursor-pointer"
            style={{
              background: settings.autoApprove
                ? "var(--forge-accent)"
                : "var(--forge-border)",
            }}
          >
            <span
              className="absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-transform"
              style={{ left: settings.autoApprove ? "18px" : "2px" }}
            />
          </button>
        </div>
      </div>
    </div>
  );
}
