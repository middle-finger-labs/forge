import { create } from "zustand";
import { invoke } from "@tauri-apps/api/core";
import type { AgentRole } from "@/types/agent";

// ─── Types ───────────────────────────────────────────

export type NotificationLevel = "all" | "approvals" | "errors" | "none";
export type ThemeMode = "dark" | "light" | "system";

export interface AgentSettings {
  model?: string;
  verbosity?: "concise" | "normal" | "verbose";
  autoApprove?: boolean;
}

export interface DndSchedule {
  enabled: boolean;
  startHour: number;  // 0-23
  endHour: number;    // 0-23
}

interface SettingsState {
  // General
  theme: ThemeMode;

  // Notifications
  notificationLevel: NotificationLevel;
  notificationSound: boolean;
  dndSchedule: DndSchedule;

  // Window behavior
  closeToTray: boolean;
  startMinimized: boolean;
  autoLaunch: boolean;

  // API Keys
  apiKeys: Array<{ id: string; name: string; prefix: string; createdAt: string }>;

  // Agent settings
  agentSettings: Partial<Record<AgentRole, AgentSettings>>;

  // Persistence
  _loaded: boolean;

  // Actions
  setTheme: (theme: ThemeMode) => void;
  setNotificationLevel: (level: NotificationLevel) => void;
  setNotificationSound: (enabled: boolean) => void;
  setDndSchedule: (schedule: DndSchedule) => void;
  setCloseToTray: (enabled: boolean) => void;
  setStartMinimized: (enabled: boolean) => void;
  setAutoLaunch: (enabled: boolean) => void;
  setAgentSettings: (role: AgentRole, settings: AgentSettings) => void;
  setApiKeys: (keys: SettingsState["apiKeys"]) => void;
  loadSettings: () => void;
}

// ─── Persistence ─────────────────────────────────────

const SETTINGS_KEY = "forge-settings";

interface PersistedSettings {
  theme?: ThemeMode;
  notificationLevel?: NotificationLevel;
  notificationSound?: boolean;
  dndSchedule?: DndSchedule;
  closeToTray?: boolean;
  startMinimized?: boolean;
  autoLaunch?: boolean;
  agentSettings?: Partial<Record<AgentRole, AgentSettings>>;
}

function loadPersistedSettings(): PersistedSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return {};
}

function persistSettings(state: SettingsState) {
  try {
    const data: PersistedSettings = {
      theme: state.theme,
      notificationLevel: state.notificationLevel,
      notificationSound: state.notificationSound,
      dndSchedule: state.dndSchedule,
      closeToTray: state.closeToTray,
      startMinimized: state.startMinimized,
      autoLaunch: state.autoLaunch,
      agentSettings: state.agentSettings,
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(data));
  } catch { /* ignore */ }
}

// ─── Theme application ──────────────────────────────

const DARK_THEME = {
  "--forge-bg": "#1a1d21",
  "--forge-sidebar": "#19171d",
  "--forge-channel": "#222529",
  "--forge-text": "#d1d2d3",
  "--forge-text-muted": "#ababad",
  "--forge-accent": "#4a9eff",
  "--forge-border": "#35373b",
  "--forge-hover": "#27242c",
  "--forge-active": "#1164a3",
  "--forge-success": "#2bac76",
  "--forge-warning": "#e8a820",
  "--forge-error": "#e84040",
};

const LIGHT_THEME: Record<string, string> = {
  "--forge-bg": "#ffffff",
  "--forge-sidebar": "#f8f8fa",
  "--forge-channel": "#ffffff",
  "--forge-text": "#1d1c1d",
  "--forge-text-muted": "#616061",
  "--forge-accent": "#1264a3",
  "--forge-border": "#dddddd",
  "--forge-hover": "#f0f0f0",
  "--forge-active": "#1164a3",
  "--forge-success": "#007a5a",
  "--forge-warning": "#e8912d",
  "--forge-error": "#e01e5a",
};

function applyTheme(mode: ThemeMode) {
  const prefersDark =
    mode === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : mode === "dark";

  const vars = prefersDark ? DARK_THEME : LIGHT_THEME;
  const root = document.documentElement;
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value);
  }
}

// ─── Store ───────────────────────────────────────────

const saved = loadPersistedSettings();

export const useSettingsStore = create<SettingsState>((set, get) => ({
  theme: saved.theme ?? "dark",
  notificationLevel: saved.notificationLevel ?? "all",
  notificationSound: saved.notificationSound ?? true,
  dndSchedule: saved.dndSchedule ?? { enabled: false, startHour: 22, endHour: 8 },
  closeToTray: saved.closeToTray ?? true,
  startMinimized: saved.startMinimized ?? false,
  autoLaunch: saved.autoLaunch ?? false,
  apiKeys: [],
  agentSettings: saved.agentSettings ?? {},
  _loaded: false,

  setTheme: (theme) => {
    set({ theme });
    applyTheme(theme);
    persistSettings(get());
  },

  setNotificationLevel: (level) => {
    set({ notificationLevel: level });
    persistSettings(get());
  },

  setNotificationSound: (enabled) => {
    set({ notificationSound: enabled });
    persistSettings(get());
  },

  setDndSchedule: (schedule) => {
    set({ dndSchedule: schedule });
    persistSettings(get());
  },

  setCloseToTray: (enabled) => {
    set({ closeToTray: enabled });
    invoke("set_close_to_tray", { enabled }).catch(console.error);
    persistSettings(get());
  },

  setStartMinimized: (enabled) => {
    set({ startMinimized: enabled });
    persistSettings(get());
  },

  setAutoLaunch: (enabled) => {
    set({ autoLaunch: enabled });
    if (enabled) {
      import("@tauri-apps/plugin-autostart").then((m) =>
        m.enable().catch(console.error)
      );
    } else {
      import("@tauri-apps/plugin-autostart").then((m) =>
        m.disable().catch(console.error)
      );
    }
    persistSettings(get());
  },

  setAgentSettings: (role, settings) => {
    set((s) => ({
      agentSettings: { ...s.agentSettings, [role]: { ...s.agentSettings[role], ...settings } },
    }));
    persistSettings(get());
  },

  setApiKeys: (keys) => set({ apiKeys: keys }),

  loadSettings: () => {
    const s = loadPersistedSettings();
    set({
      theme: s.theme ?? "dark",
      notificationLevel: s.notificationLevel ?? "all",
      notificationSound: s.notificationSound ?? true,
      dndSchedule: s.dndSchedule ?? { enabled: false, startHour: 22, endHour: 8 },
      closeToTray: s.closeToTray ?? true,
      startMinimized: s.startMinimized ?? false,
      autoLaunch: s.autoLaunch ?? false,
      agentSettings: s.agentSettings ?? {},
      _loaded: true,
    });
    applyTheme(s.theme ?? "dark");
  },
}));

// Apply theme on initial load
applyTheme(saved.theme ?? "dark");
