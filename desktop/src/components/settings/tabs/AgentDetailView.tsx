import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { AGENT_REGISTRY, type AgentRole } from "@/types/agent";
import { AgentConfigTab } from "./AgentConfigTab";
import { PromptLabTab } from "./PromptLabTab";
import { LessonsTab } from "./LessonsTab";

type AgentSubTab = "config" | "prompt-lab" | "lessons";

const SUB_TABS: Array<{ key: AgentSubTab; label: string }> = [
  { key: "config", label: "Configuration" },
  { key: "prompt-lab", label: "Prompt Lab" },
  { key: "lessons", label: "Lessons" },
];

interface AgentDetailViewProps {
  role: AgentRole;
  onBack: () => void;
}

export function AgentDetailView({ role, onBack }: AgentDetailViewProps) {
  const [activeTab, setActiveTab] = useState<AgentSubTab>("config");
  const info = AGENT_REGISTRY[role];

  return (
    <div className="space-y-4">
      {/* Header with back button */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="p-1 rounded transition-colors cursor-pointer hover:bg-[var(--forge-hover)]"
          style={{ color: "var(--forge-text-muted)" }}
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="text-lg">{info.emoji}</span>
        <h2
          className="text-sm font-semibold"
          style={{ color: "var(--forge-text)" }}
        >
          {info.displayName}
        </h2>
      </div>

      {/* Sub-tab bar */}
      <div
        className="flex gap-1"
        style={{ borderBottom: "1px solid var(--forge-border)" }}
      >
        {SUB_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className="px-3 py-2 text-xs font-medium transition-colors cursor-pointer relative"
            style={{
              color:
                activeTab === tab.key
                  ? "var(--forge-accent)"
                  : "var(--forge-text-muted)",
            }}
          >
            {tab.label}
            {activeTab === tab.key && (
              <span
                className="absolute bottom-0 left-0 right-0 h-0.5"
                style={{ background: "var(--forge-accent)" }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "config" && <AgentConfigTab role={role} />}
      {activeTab === "prompt-lab" && <PromptLabTab role={role} />}
      {activeTab === "lessons" && <LessonsTab role={role} />}
    </div>
  );
}
