import { useState, useEffect, useCallback, useRef } from "react";
import { usePlatform } from "./usePlatform";
import {
  loadSecureSession,
  saveSecureSession,
  clearSecureSession,
  hasValidSecureSession,
  type SecureSession,
} from "@/lib/secureStorage";

// ─── Types ───────────────────────────────────────────

export type BiometryType = "faceId" | "touchId" | "fingerprint" | "none";

interface BiometricAuthState {
  /** Whether biometric hardware is available on this device. */
  available: boolean;
  /** The type of biometric: faceId, touchId, fingerprint, or none. */
  biometryType: BiometryType;
  /** Whether the user has enrolled (opted in) for biometric auth. */
  enrolled: boolean;
  /** Whether a valid (non-expired) secure session exists. */
  hasSession: boolean;
  /** Number of consecutive failed biometric attempts this session. */
  failCount: number;
  /** Whether biometric is locked out (3+ failures). */
  lockedOut: boolean;

  /** Prompt biometric authentication. Resolves true on success. */
  promptBiometric: () => Promise<boolean>;
  /** Enable biometric auth by saving the current session. */
  enroll: (session: Omit<SecureSession, "enrolledAt">) => void;
  /** Disable biometric auth and clear the stored session. */
  unenroll: () => void;
  /** Load the stored session (only call after successful biometric). */
  getSession: () => SecureSession | null;
  /** Reset the fail counter (e.g., after successful password login). */
  resetFailCount: () => void;
}

// ─── Constants ───────────────────────────────────────

const MAX_BIOMETRIC_FAILURES = 3;

// ─── Hook ────────────────────────────────────────────

export function useBiometricAuth(): BiometricAuthState {
  const { isMobile } = usePlatform();
  const [available, setAvailable] = useState(false);
  const [biometryType, setBiometryType] = useState<BiometryType>("none");
  const [enrolled, setEnrolled] = useState(false);
  const [hasSession, setHasSession] = useState(false);
  const [failCount, setFailCount] = useState(0);
  const checkDone = useRef(false);

  // Check biometric availability on mount (mobile only)
  useEffect(() => {
    if (!isMobile || checkDone.current) return;
    checkDone.current = true;

    (async () => {
      try {
        const biometric = await import("@tauri-apps/plugin-biometric");
        const status = await biometric.checkStatus();

        setAvailable(status.isAvailable);

        // Map the biometryType string
        if (status.biometryType) {
          const typeStr = status.biometryType.toString().toLowerCase();
          if (typeStr.includes("face")) {
            setBiometryType("faceId");
          } else if (typeStr.includes("touch")) {
            setBiometryType("touchId");
          } else if (typeStr.includes("finger")) {
            setBiometryType("fingerprint");
          }
        }
      } catch {
        // Biometric not available (desktop, or plugin not loaded)
        setAvailable(false);
      }
    })();
  }, [isMobile]);

  // Check enrollment status from secure storage
  useEffect(() => {
    const valid = hasValidSecureSession();
    setHasSession(valid);
    setEnrolled(valid);
  }, []);

  // Prompt biometric authentication
  const promptBiometric = useCallback(async (): Promise<boolean> => {
    if (!available || failCount >= MAX_BIOMETRIC_FAILURES) {
      return false;
    }

    try {
      const biometric = await import("@tauri-apps/plugin-biometric");
      await biometric.authenticate("Authenticate to access Forge", {
        allowDeviceCredential: true, // fallback to PIN/password
        title: "Forge Authentication",
        subtitle: "Verify your identity",
        confirmationRequired: false,
      } as never);

      // Success — reset fail count
      setFailCount(0);
      return true;
    } catch {
      // Biometric failed or was cancelled
      setFailCount((prev) => {
        const next = prev + 1;
        if (next >= MAX_BIOMETRIC_FAILURES) {
          console.warn(
            `[Biometric] Locked out after ${MAX_BIOMETRIC_FAILURES} failed attempts`,
          );
        }
        return next;
      });
      return false;
    }
  }, [available, failCount]);

  // Enroll: save session and mark as enrolled
  const enroll = useCallback(
    (session: Omit<SecureSession, "enrolledAt">) => {
      saveSecureSession({
        ...session,
        enrolledAt: Date.now(),
      });
      setEnrolled(true);
      setHasSession(true);
    },
    [],
  );

  // Unenroll: clear stored session
  const unenroll = useCallback(() => {
    clearSecureSession();
    setEnrolled(false);
    setHasSession(false);
  }, []);

  // Get stored session
  const getSession = useCallback((): SecureSession | null => {
    return loadSecureSession();
  }, []);

  // Reset fail counter
  const resetFailCount = useCallback(() => {
    setFailCount(0);
  }, []);

  return {
    available,
    biometryType,
    enrolled,
    hasSession,
    failCount,
    lockedOut: failCount >= MAX_BIOMETRIC_FAILURES,
    promptBiometric,
    enroll,
    unenroll,
    getSession,
    resetFailCount,
  };
}

// ─── Display helpers ─────────────────────────────────

/** Get a user-friendly name for the biometry type. */
export function biometryDisplayName(type: BiometryType): string {
  switch (type) {
    case "faceId":
      return "Face ID";
    case "touchId":
      return "Touch ID";
    case "fingerprint":
      return "Fingerprint";
    default:
      return "Biometric";
  }
}
