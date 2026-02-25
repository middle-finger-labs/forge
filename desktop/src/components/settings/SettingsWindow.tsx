import { useState } from "react";
import {
  Settings,
  Bell,
  Key,
  Bot,
  Info,
  X,
} from "lucide-react";
import { GeneralTab } from "./tabs/GeneralTab";
import { NotificationsTab } from "./tabs/NotificationsTab";
import { ApiKeysTab } from "./tabs/ApiKeysTab";
import { AgentsTab } from "./tabs/AgentsTab";
import { AboutTab } from "./tabs/AboutTab";

type SettingsTab = "general" | "notifications" | "api-keys" | "agents" | "about";

const TABS: Array<{ id: SettingsTab; label: string; icon: typeof Settings }> = [
  { id: "general", label: "General", icon: Settings },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "api-keys", label: "API Keys", icon: Key },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "about", label: "About", icon: Info },
];

interface SettingsWindowProps {
  onClose: () => void;
}

export function SettingsWindow({ onClose }: SettingsWindowProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  return (
    <div
      className="h-full flex flex-col"
      style={{ background: "var(--forge-bg)" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-6 py-4 shrink-0"
        style={{ borderBottom: "1px solid var(--forge-border)" }}
      >
        <h1 className="text-lg font-bold" style={{ color: "var(--forge-text)" }}>
          Settings
        </h1>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md transition-colors cursor-pointer"
          style={{ color: "var(--forge-text-muted)" }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.background = "var(--forge-hover)")
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.background = "transparent")
          }
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Tab sidebar */}
        <nav
          className="w-52 shrink-0 py-3 px-3 overflow-y-auto"
          style={{ borderRight: "1px solid var(--forge-border)" }}
        >
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors cursor-pointer mb-0.5"
                style={{
                  background: isActive ? "var(--forge-hover)" : "transparent",
                  color: isActive
                    ? "var(--forge-text)"
                    : "var(--forge-text-muted)",
                }}
                onMouseEnter={(e) => {
                  if (!isActive)
                    e.currentTarget.style.background = "var(--forge-hover)";
                }}
                onMouseLeave={(e) => {
                  if (!isActive)
                    e.currentTarget.style.background = "transparent";
                }}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </nav>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeTab === "general" && <GeneralTab />}
          {activeTab === "notifications" && <NotificationsTab />}
          {activeTab === "api-keys" && <ApiKeysTab />}
          {activeTab === "agents" && <AgentsTab />}
          {activeTab === "about" && <AboutTab />}
        </div>
      </div>
    </div>
  );
}
