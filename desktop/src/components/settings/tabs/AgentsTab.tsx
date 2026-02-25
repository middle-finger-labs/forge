import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { AGENT_REGISTRY, AGENT_ROLES, type AgentRole } from "@/types/agent";
import { Section } from "./GeneralTab";
import { AgentDetailView } from "./AgentDetailView";

export function AgentsTab() {
  const [selectedAgent, setSelectedAgent] = useState<AgentRole | null>(null);
  const { agentSettings } = useSettingsStore();

  if (selectedAgent) {
    return (
      <AgentDetailView
        role={selectedAgent}
        onBack={() => setSelectedAgent(null)}
      />
    );
  }

  return (
    <div className="max-w-lg space-y-6">
      <Section title="Agent Configuration">
        <p className="text-xs mb-4" style={{ color: "var(--forge-text-muted)" }}>
          Customize how each agent behaves. Click an agent to edit prompts,
          view lessons, and configure settings.
        </p>
      </Section>

      {AGENT_ROLES.map((role) => {
        const info = AGENT_REGISTRY[role];
        const settings = agentSettings[role];
        const model = settings?.model ?? "Auto";
        return (
          <button
            key={role}
            onClick={() => setSelectedAgent(role)}
            className="w-full rounded-lg p-4 text-left transition-colors cursor-pointer"
            style={{
              background: "var(--forge-channel)",
              border: "1px solid var(--forge-border)",
            }}
          >
            <div className="flex items-center gap-3">
              <span className="text-lg">{info.emoji}</span>
              <div className="flex-1 min-w-0">
                <span
                  className="text-sm font-medium block"
                  style={{ color: "var(--forge-text)" }}
                >
                  {info.displayName}
                </span>
                <span
                  className="text-[11px]"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  {model}
                  {settings?.autoApprove ? " · Auto-approve" : ""}
                </span>
              </div>
              <ChevronRight
                className="w-4 h-4 shrink-0"
                style={{ color: "var(--forge-text-muted)" }}
              />
            </div>
          </button>
        );
      })}
    </div>
  );
}
