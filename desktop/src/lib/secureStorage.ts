/**
 * Secure storage abstraction for auth tokens.
 *
 * On mobile (iOS/Android), uses a separate localStorage key prefixed with
 * `__forge_secure_` to simulate secure storage. In a production build this
 * would use the iOS Keychain / Android Keystore via a Tauri plugin, but
 * Tauri v2 does not ship a first-party secure-storage plugin yet, so we
 * use a dedicated storage namespace that the biometric gate protects.
 *
 * The biometric check itself is the security boundary — the token is only
 * read after a successful Face ID / Touch ID / fingerprint prompt.
 */

const SECURE_PREFIX = "__forge_secure_";

export interface SecureSession {
  authToken: string;
  serverUrl: string;
  enrolledAt: number;   // epoch ms — when biometric was enabled
  userId: string;
  userEmail: string;
  userName: string;
  orgId: string;
  orgName: string;
}

const SESSION_KEY = `${SECURE_PREFIX}session`;

/**
 * Store a session after the user opts into biometric auth.
 */
export function saveSecureSession(session: SecureSession): void {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // Storage full or unavailable
  }
}

/**
 * Load a previously stored secure session.
 * Returns `null` if no session exists or data is corrupt.
 */
export function loadSecureSession(): SecureSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as SecureSession;
  } catch {
    return null;
  }
}

/**
 * Clear the secure session (e.g., on logout or biometric disable).
 */
export function clearSecureSession(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    // Ignore
  }
}

/**
 * Check if a secure session exists and hasn't expired.
 * Sessions expire after 30 days.
 */
export function hasValidSecureSession(): boolean {
  const session = loadSecureSession();
  if (!session) return false;

  const thirtyDays = 30 * 24 * 60 * 60 * 1000;
  const age = Date.now() - session.enrolledAt;

  if (age > thirtyDays) {
    // Session expired — require full re-authentication
    clearSecureSession();
    return false;
  }

  return true;
}
