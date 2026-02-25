import { useSettingsStore, type ThemeMode } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { Monitor, Moon, Sun } from "lucide-react";

const THEME_OPTIONS: Array<{ value: ThemeMode; label: string; icon: typeof Sun }> = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export function GeneralTab() {
  const { theme, setTheme, closeToTray, setCloseToTray, startMinimized, setStartMinimized, autoLaunch, setAutoLaunch } =
    useSettingsStore();
  const { serverUrl } = useConnectionStore();

  return (
    <div className="max-w-lg space-y-8">
      {/* Server */}
      <Section title="Connection">
        <SettingRow label="Server URL" description="The Forge server you're connected to">
          <div
            className="text-sm px-3 py-1.5 rounded-md"
            style={{
              background: "var(--forge-channel)",
              color: "var(--forge-text-muted)",
              border: "1px solid var(--forge-border)",
            }}
          >
            {serverUrl || "Not configured"}
          </div>
        </SettingRow>
      </Section>

      {/* Appearance */}
      <Section title="Appearance">
        <SettingRow label="Theme" description="Choose how Forge looks">
          <div className="flex gap-1">
            {THEME_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const isActive = theme === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => setTheme(opt.value)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                  style={{
                    background: isActive ? "var(--forge-accent)" : "var(--forge-channel)",
                    color: isActive ? "#fff" : "var(--forge-text-muted)",
                    border: `1px solid ${isActive ? "var(--forge-accent)" : "var(--forge-border)"}`,
                  }}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {opt.label}
                </button>
              );
            })}
          </div>
        </SettingRow>
      </Section>

      {/* Window */}
      <Section title="Window Behavior">
        <ToggleRow
          label="Close to tray"
          description="Keep Forge running in the system tray when the window is closed"
          checked={closeToTray}
          onChange={setCloseToTray}
        />
        <ToggleRow
          label="Start minimized"
          description="Launch Forge minimized to the system tray"
          checked={startMinimized}
          onChange={setStartMinimized}
        />
        <ToggleRow
          label="Launch on startup"
          description="Automatically start Forge when you log in"
          checked={autoLaunch}
          onChange={setAutoLaunch}
        />
      </Section>
    </div>
  );
}

// ─── Shared sub-components ───────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2
        className="text-sm font-semibold mb-4"
        style={{ color: "var(--forge-text)" }}
      >
        {title}
      </h2>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="text-sm" style={{ color: "var(--forge-text)" }}>
          {label}
        </div>
        {description && (
          <div className="text-xs mt-0.5" style={{ color: "var(--forge-text-muted)" }}>
            {description}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <SettingRow label={label} description={description}>
      <button
        onClick={() => onChange(!checked)}
        className="relative w-10 h-5 rounded-full shrink-0 transition-colors cursor-pointer"
        style={{
          background: checked ? "var(--forge-accent)" : "var(--forge-border)",
        }}
      >
        <span
          className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
          style={{ left: checked ? "22px" : "2px" }}
        />
      </button>
    </SettingRow>
  );
}

export { Section, SettingRow, ToggleRow };
