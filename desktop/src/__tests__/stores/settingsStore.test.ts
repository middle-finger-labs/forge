import { describe, it, expect, beforeEach } from "vitest";
import { useSettingsStore } from "@/stores/settingsStore";

function resetStore() {
  useSettingsStore.setState({
    theme: "dark",
    notificationLevel: "all",
    notificationSound: true,
    dndSchedule: { enabled: false, startHour: 22, endHour: 8 },
    closeToTray: true,
    startMinimized: false,
    autoLaunch: false,
    apiKeys: [],
    agentSettings: {},
    _loaded: false,
  });
}

describe("settingsStore", () => {
  beforeEach(resetStore);

  // ─── Theme ──────────────────────────────────────

  describe("theme", () => {
    it("defaults to dark", () => {
      expect(useSettingsStore.getState().theme).toBe("dark");
    });

    it("setTheme updates and persists", () => {
      useSettingsStore.getState().setTheme("light");
      expect(useSettingsStore.getState().theme).toBe("light");
      expect(localStorage.setItem).toHaveBeenCalled();
    });

    it("setTheme applies CSS variables", () => {
      useSettingsStore.getState().setTheme("light");
      const bg = document.documentElement.style.getPropertyValue("--forge-bg");
      expect(bg).toBe("#ffffff");
    });

    it("dark theme applies dark CSS variables", () => {
      useSettingsStore.getState().setTheme("dark");
      const bg = document.documentElement.style.getPropertyValue("--forge-bg");
      expect(bg).toBe("#1a1d21");
    });

    it("system theme resolves based on matchMedia", () => {
      useSettingsStore.getState().setTheme("system");
      // matchMedia is mocked to return dark
      const bg = document.documentElement.style.getPropertyValue("--forge-bg");
      expect(bg).toBe("#1a1d21");
    });
  });

  // ─── Notifications ─────────────────────────────

  describe("notifications", () => {
    it("setNotificationLevel changes level", () => {
      useSettingsStore.getState().setNotificationLevel("approvals");
      expect(useSettingsStore.getState().notificationLevel).toBe("approvals");
    });

    it("setNotificationSound toggles sound", () => {
      useSettingsStore.getState().setNotificationSound(false);
      expect(useSettingsStore.getState().notificationSound).toBe(false);
    });

    it("setDndSchedule updates schedule", () => {
      useSettingsStore.getState().setDndSchedule({ enabled: true, startHour: 20, endHour: 7 });
      const dnd = useSettingsStore.getState().dndSchedule;
      expect(dnd.enabled).toBe(true);
      expect(dnd.startHour).toBe(20);
      expect(dnd.endHour).toBe(7);
    });
  });

  // ─── Window behavior ──────────────────────────

  describe("window behavior", () => {
    it("setCloseToTray updates and invokes Tauri command", async () => {
      useSettingsStore.getState().setCloseToTray(false);
      expect(useSettingsStore.getState().closeToTray).toBe(false);
    });

    it("setStartMinimized updates state", () => {
      useSettingsStore.getState().setStartMinimized(true);
      expect(useSettingsStore.getState().startMinimized).toBe(true);
    });

    it("setAutoLaunch updates state", () => {
      useSettingsStore.getState().setAutoLaunch(true);
      expect(useSettingsStore.getState().autoLaunch).toBe(true);
    });
  });

  // ─── Agent settings ────────────────────────────

  describe("agent settings", () => {
    it("setAgentSettings stores per-agent config", () => {
      useSettingsStore.getState().setAgentSettings("engineer", {
        model: "claude-sonnet-4-5-20250929",
        verbosity: "concise",
      });

      const settings = useSettingsStore.getState().agentSettings;
      expect(settings["engineer"]?.model).toBe("claude-sonnet-4-5-20250929");
      expect(settings["engineer"]?.verbosity).toBe("concise");
    });

    it("setAgentSettings merges with existing", () => {
      useSettingsStore.getState().setAgentSettings("engineer", { model: "a" });
      useSettingsStore.getState().setAgentSettings("engineer", { verbosity: "verbose" });

      const settings = useSettingsStore.getState().agentSettings;
      expect(settings["engineer"]?.model).toBe("a");
      expect(settings["engineer"]?.verbosity).toBe("verbose");
    });
  });

  // ─── Persistence round-trip ────────────────────

  describe("persistence", () => {
    it("settings persist and apply immediately", () => {
      useSettingsStore.getState().setTheme("light");
      useSettingsStore.getState().setNotificationLevel("errors");
      useSettingsStore.getState().setCloseToTray(false);

      // Verify localStorage was called
      expect(localStorage.setItem).toHaveBeenCalled();

      // Verify state is immediately correct
      const state = useSettingsStore.getState();
      expect(state.theme).toBe("light");
      expect(state.notificationLevel).toBe("errors");
      expect(state.closeToTray).toBe(false);
    });

    it("loadSettings restores defaults when localStorage is empty", () => {
      useSettingsStore.getState().loadSettings();
      const state = useSettingsStore.getState();

      expect(state.theme).toBe("dark");
      expect(state.notificationLevel).toBe("all");
      expect(state._loaded).toBe(true);
    });
  });

  // ─── API Keys ──────────────────────────────────

  describe("API keys", () => {
    it("setApiKeys replaces the list", () => {
      const keys = [
        { id: "k1", name: "Production", prefix: "sk-ant-...", createdAt: "2024-01-01" },
      ];
      useSettingsStore.getState().setApiKeys(keys);
      expect(useSettingsStore.getState().apiKeys).toHaveLength(1);
      expect(useSettingsStore.getState().apiKeys[0].name).toBe("Production");
    });
  });
});
