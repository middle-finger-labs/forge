import { useCallback } from "react";
import { ScanFace, Fingerprint, ShieldCheck, X } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import {
  useBiometricAuth,
  biometryDisplayName,
} from "@/hooks/useBiometricAuth";
import { cn } from "@/lib/utils";

// ─── Props ──────────────────────────────────────────

interface BiometricEnrollSheetProps {
  onClose: () => void;
}

// ─── Component ──────────────────────────────────────

/**
 * Bottom sheet shown after first successful login on mobile.
 * Offers the user to enable Face ID / Touch ID / Fingerprint
 * for quick access on subsequent app opens.
 */
export function BiometricEnrollSheet({ onClose }: BiometricEnrollSheetProps) {
  const { user, org, serverUrl, authToken } = useConnectionStore();
  const { setBiometricEnabled, setBiometricPromptShown } = useSettingsStore();
  const biometric = useBiometricAuth();

  const BiometricIcon =
    biometric.biometryType === "faceId" ? ScanFace : Fingerprint;
  const biometricLabel = biometryDisplayName(biometric.biometryType);

  const handleEnable = useCallback(async () => {
    if (!user || !org || !authToken) return;

    // Verify biometric works before enrolling
    const success = await biometric.promptBiometric();
    if (success) {
      // Save session to secure storage
      biometric.enroll({
        authToken,
        serverUrl,
        userId: user.id,
        userEmail: user.email,
        userName: user.name,
        orgId: org.id,
        orgName: org.name,
      });

      setBiometricEnabled(true);
      setBiometricPromptShown(true);
      onClose();
    }
  }, [
    user,
    org,
    authToken,
    serverUrl,
    biometric,
    setBiometricEnabled,
    setBiometricPromptShown,
    onClose,
  ]);

  const handleSkip = useCallback(() => {
    setBiometricPromptShown(true);
    onClose();
  }, [setBiometricPromptShown, onClose]);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-50" onClick={handleSkip} />

      {/* Sheet */}
      <div className="fixed inset-x-0 bottom-0 z-50 bg-[var(--forge-bg)] rounded-t-3xl border-t border-[var(--forge-border)] pb-[env(safe-area-inset-bottom)]">
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-2">
          <div className="w-10 h-1 rounded-full bg-[var(--forge-border)]" />
        </div>

        {/* Close button */}
        <button
          onClick={handleSkip}
          className="absolute top-4 right-4 p-2 text-[var(--forge-text-muted)] active:text-[var(--forge-text)]"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Content */}
        <div className="px-6 pt-4 pb-6">
          <div className="flex flex-col items-center text-center mb-6">
            <div className="w-16 h-16 rounded-2xl bg-[var(--forge-accent)]/10 flex items-center justify-center mb-4">
              <BiometricIcon className="w-8 h-8 text-[var(--forge-accent)]" />
            </div>
            <h2 className="text-lg font-bold text-white mb-1.5">
              Enable {biometricLabel}?
            </h2>
            <p className="text-sm text-[var(--forge-text-muted)] max-w-[280px]">
              Use {biometricLabel} for quick access to Forge without entering
              your password each time.
            </p>
          </div>

          {/* Security note */}
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-[var(--forge-sidebar)] mb-6">
            <ShieldCheck className="w-4 h-4 text-[var(--forge-success)] shrink-0 mt-0.5" />
            <p className="text-xs text-[var(--forge-text-muted)] leading-relaxed">
              Your session is stored securely and protected by {biometricLabel}.
              You'll need to sign in again after 30 days.
            </p>
          </div>

          {/* Actions */}
          <div className="space-y-3">
            <button
              onClick={handleEnable}
              className={cn(
                "w-full flex items-center justify-center gap-2 py-3.5 rounded-xl",
                "text-sm font-medium text-white",
                "bg-[var(--forge-accent)] active:opacity-80",
                "min-h-[48px]",
              )}
            >
              <BiometricIcon className="w-5 h-5" />
              Enable {biometricLabel}
            </button>
            <button
              onClick={handleSkip}
              className={cn(
                "w-full py-3.5 rounded-xl text-sm font-medium",
                "text-[var(--forge-text-muted)]",
                "active:bg-[var(--forge-hover)]",
                "min-h-[48px]",
              )}
            >
              Not now
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
