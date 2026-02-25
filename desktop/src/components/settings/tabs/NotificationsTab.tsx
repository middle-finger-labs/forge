import { useSettingsStore, type NotificationLevel } from "@/stores/settingsStore";
import { Section, SettingRow, ToggleRow } from "./GeneralTab";

const LEVELS: Array<{ value: NotificationLevel; label: string; description: string }> = [
  { value: "all", label: "All", description: "Get notified about everything" },
  { value: "approvals", label: "Approvals only", description: "Only approval requests and completions" },
  { value: "errors", label: "Errors only", description: "Only errors and failures" },
  { value: "none", label: "None", description: "No notifications" },
];

export function NotificationsTab() {
  const {
    notificationLevel,
    setNotificationLevel,
    notificationSound,
    setNotificationSound,
    dndSchedule,
    setDndSchedule,
  } = useSettingsStore();

  return (
    <div className="max-w-lg space-y-8">
      {/* Level */}
      <Section title="Notification Level">
        <div className="space-y-2">
          {LEVELS.map((level) => (
            <label
              key={level.value}
              className="flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors"
              style={{
                background:
                  notificationLevel === level.value
                    ? "var(--forge-hover)"
                    : "transparent",
                border: `1px solid ${
                  notificationLevel === level.value
                    ? "var(--forge-accent)"
                    : "var(--forge-border)"
                }`,
              }}
            >
              <input
                type="radio"
                name="notificationLevel"
                checked={notificationLevel === level.value}
                onChange={() => setNotificationLevel(level.value)}
                className="mt-0.5 accent-[var(--forge-accent)]"
              />
              <div>
                <div className="text-sm" style={{ color: "var(--forge-text)" }}>
                  {level.label}
                </div>
                <div
                  className="text-xs mt-0.5"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  {level.description}
                </div>
              </div>
            </label>
          ))}
        </div>
      </Section>

      {/* Sound */}
      <Section title="Sound">
        <ToggleRow
          label="Notification sound"
          description="Play a sound when notifications arrive"
          checked={notificationSound}
          onChange={setNotificationSound}
        />
      </Section>

      {/* DND */}
      <Section title="Do Not Disturb">
        <ToggleRow
          label="Enable schedule"
          description="Mute notifications during set hours"
          checked={dndSchedule.enabled}
          onChange={(enabled) =>
            setDndSchedule({ ...dndSchedule, enabled })
          }
        />

        {dndSchedule.enabled && (
          <SettingRow label="Quiet hours">
            <div className="flex items-center gap-2">
              <TimeSelect
                value={dndSchedule.startHour}
                onChange={(h) =>
                  setDndSchedule({ ...dndSchedule, startHour: h })
                }
              />
              <span
                className="text-xs"
                style={{ color: "var(--forge-text-muted)" }}
              >
                to
              </span>
              <TimeSelect
                value={dndSchedule.endHour}
                onChange={(h) =>
                  setDndSchedule({ ...dndSchedule, endHour: h })
                }
              />
            </div>
          </SettingRow>
        )}
      </Section>
    </div>
  );
}

function TimeSelect({
  value,
  onChange,
}: {
  value: number;
  onChange: (h: number) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-2 py-1 rounded-md text-xs cursor-pointer outline-none"
      style={{
        background: "var(--forge-channel)",
        color: "var(--forge-text)",
        border: "1px solid var(--forge-border)",
      }}
    >
      {Array.from({ length: 24 }, (_, i) => (
        <option key={i} value={i}>
          {i.toString().padStart(2, "0")}:00
        </option>
      ))}
    </select>
  );
}
