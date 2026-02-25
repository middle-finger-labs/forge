import { invoke } from "@tauri-apps/api/core";

/**
 * Secure storage service for sensitive data (auth tokens, etc.).
 *
 * Uses the OS keychain via Tauri Rust commands on desktop.
 * Falls back to localStorage if keyring is unavailable (e.g. web dev mode).
 */

const FALLBACK_PREFIX = "__forge_secure_";

async function isTauriAvailable(): Promise<boolean> {
  try {
    return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  } catch {
    return false;
  }
}

export async function saveSecureToken(key: string, value: string): Promise<void> {
  if (await isTauriAvailable()) {
    try {
      await invoke("save_secure_data", { key, value });
      return;
    } catch (err) {
      console.warn("[SecureStorage] Keyring save failed, falling back to localStorage:", err);
    }
  }
  try {
    localStorage.setItem(`${FALLBACK_PREFIX}${key}`, value);
  } catch { /* ignore */ }
}

export async function getSecureToken(key: string): Promise<string | null> {
  if (await isTauriAvailable()) {
    try {
      const result = await invoke<string | null>("get_secure_data", { key });
      if (result !== null) return result;
      // Fall through to check localStorage in case of migration
    } catch (err) {
      console.warn("[SecureStorage] Keyring read failed, falling back to localStorage:", err);
    }
  }
  try {
    return localStorage.getItem(`${FALLBACK_PREFIX}${key}`);
  } catch {
    return null;
  }
}

export async function deleteSecureToken(key: string): Promise<void> {
  if (await isTauriAvailable()) {
    try {
      await invoke("delete_secure_data", { key });
    } catch (err) {
      console.warn("[SecureStorage] Keyring delete failed:", err);
    }
  }
  try {
    localStorage.removeItem(`${FALLBACK_PREFIX}${key}`);
  } catch { /* ignore */ }
}
