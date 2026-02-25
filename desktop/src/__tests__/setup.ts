import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// ─── Mock Tauri APIs ─────────────────────────────────────────
// These modules are only available inside a Tauri webview,
// so we stub them for JSDOM-based tests.

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string, _args?: Record<string, unknown>) => {
    switch (cmd) {
      case "get_forge_api_url":
        return "http://localhost:8000";
      case "get_app_version":
        return "0.1.0";
      case "get_connection_status":
        return "connected";
      default:
        return undefined;
    }
  }),
}));

vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(async () => true),
  requestPermission: vi.fn(async () => "granted"),
  sendNotification: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-shell", () => ({
  open: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-websocket", () => {
  const listeners: Array<(msg: unknown) => void> = [];
  return {
    default: {
      connect: vi.fn(async () => ({
        addListener: vi.fn((cb: (msg: unknown) => void) => {
          listeners.push(cb);
        }),
        send: vi.fn(),
        disconnect: vi.fn(),
      })),
    },
    __test_listeners: listeners,
  };
});

vi.mock("@tauri-apps/plugin-autostart", () => ({
  enable: vi.fn(async () => {}),
  disable: vi.fn(async () => {}),
  isEnabled: vi.fn(async () => false),
}));

vi.mock("@tauri-apps/plugin-global-shortcut", () => ({
  register: vi.fn(),
  unregister: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-window-state", () => ({}));

// ─── Mock window.matchMedia ──────────────────────────────────

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)",
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ─── Mock localStorage ────────────────────────────────────────

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn((index: number) => Object.keys(store)[index] ?? null),
  };
})();

Object.defineProperty(window, "localStorage", { value: localStorageMock });

// ─── Reset stores between tests ──────────────────────────────

import { afterEach } from "vitest";

afterEach(() => {
  localStorageMock.clear();
  vi.clearAllMocks();
});
