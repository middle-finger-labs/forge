import { useSettingsStore, type AgentSettings } from "@/stores/settingsStore";
import type { AgentRole } from "@/types/agent";

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

export function AgentConfigTab({ role }: { role: AgentRole }) {
  const { agentSettings, setAgentSettings } = useSettingsStore();
  const settings = agentSettings[role] ?? {};
  const onChange = (s: AgentSettings) => setAgentSettings(role, s);

  return (
    <div className="space-y-4 pt-2">
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
  );
}
