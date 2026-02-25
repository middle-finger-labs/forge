import { useState, useCallback, useEffect } from "react";
import {
  Mail,
  Lock,
  ArrowRight,
  Loader2,
  AlertCircle,
  Settings,
  Fingerprint,
  ScanFace,
  ShieldCheck,
} from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import {
  useBiometricAuth,
  biometryDisplayName,
} from "@/hooks/useBiometricAuth";
import { cn } from "@/lib/utils";

// ─── Props ──────────────────────────────────────────

interface MobileLoginScreenProps {
  /** Whether to show the server URL configuration sheet. */
  onOpenServerConfig?: () => void;
}

// ─── Component ──────────────────────────────────────

export function MobileLoginScreen({
  onOpenServerConfig,
}: MobileLoginScreenProps) {
  const { login, connectionStatus, connectionError, serverUrl } =
    useConnectionStore();
  const { biometricEnabled } = useSettingsStore();
  const biometric = useBiometricAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [biometricLoading, setBiometricLoading] = useState(false);
  const isLoading = connectionStatus === "connecting";

  // Show biometric prompt if enrolled and session available
  const canUseBiometric =
    biometric.available &&
    biometric.enrolled &&
    biometric.hasSession &&
    biometricEnabled &&
    !biometric.lockedOut;

  // Auto-prompt biometric on mount if available
  useEffect(() => {
    if (canUseBiometric && !isLoading) {
      handleBiometricLogin();
    }
    // Only on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Email + password login ─────────────────────

  const handlePasswordLogin = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      try {
        await login(email, password, true);
        // Reset biometric fail count on successful password login
        biometric.resetFailCount();
      } catch {
        // Error is set in the store
      }
    },
    [email, password, login, biometric],
  );

  // ── Biometric login ────────────────────────────

  const handleBiometricLogin = useCallback(async () => {
    if (!canUseBiometric) return;

    setBiometricLoading(true);
    try {
      const success = await biometric.promptBiometric();
      if (success) {
        const session = biometric.getSession();
        if (session) {
          // Restore session from secure storage
          useConnectionStore.setState({
            serverUrl: session.serverUrl,
            authToken: session.authToken,
            user: {
              id: session.userId,
              email: session.userEmail,
              name: session.userName,
              role: "member",
              createdAt: "",
            },
            org: {
              id: session.orgId,
              name: session.orgName,
              slug: "",
              plan: "pro",
              memberCount: 0,
            },
            connectionStatus: "authenticated",
            connectionError: null,
          });

          // Validate session in background
          useConnectionStore.getState().restoreSession();
        }
      }
    } finally {
      setBiometricLoading(false);
    }
  }, [canUseBiometric, biometric]);

  // ── Biometric icon ─────────────────────────────

  const BiometricIcon =
    biometric.biometryType === "faceId" ? ScanFace : Fingerprint;
  const biometricLabel = biometryDisplayName(biometric.biometryType);

  return (
    <div
      className="min-h-[100dvh] flex flex-col"
      style={{ background: "var(--forge-bg)" }}
    >
      {/* Safe area + settings gear */}
      <div className="flex items-center justify-end px-4 pt-[env(safe-area-inset-top)] shrink-0">
        <button
          onClick={onOpenServerConfig}
          className="p-3 text-[var(--forge-text-muted)] active:text-[var(--forge-text)]"
        >
          <Settings className="w-5 h-5" />
        </button>
      </div>

      {/* Main content — centered vertically */}
      <div className="flex-1 flex flex-col justify-center px-6 pb-8">
        {/* Logo / header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-5 bg-[var(--forge-accent)]">
            <ShieldCheck className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white mb-1.5">
            Sign in to Forge
          </h1>
          <p className="text-sm text-[var(--forge-text-muted)]">
            {serverUrl || "Not connected"}
          </p>
        </div>

        {/* Biometric quick-login button */}
        {canUseBiometric && (
          <div className="mb-6">
            <button
              onClick={handleBiometricLogin}
              disabled={biometricLoading}
              className={cn(
                "w-full flex flex-col items-center gap-3 py-6 rounded-2xl",
                "bg-[var(--forge-accent)]/10 border border-[var(--forge-accent)]/30",
                "active:bg-[var(--forge-accent)]/20 transition-colors",
              )}
            >
              {biometricLoading ? (
                <Loader2 className="w-10 h-10 text-[var(--forge-accent)] animate-spin" />
              ) : (
                <BiometricIcon className="w-10 h-10 text-[var(--forge-accent)]" />
              )}
              <span className="text-sm font-medium text-[var(--forge-accent)]">
                {biometricLoading
                  ? "Authenticating..."
                  : `Sign in with ${biometricLabel}`}
              </span>
            </button>

            {biometric.lockedOut && (
              <p className="text-xs text-[var(--forge-error)] text-center mt-2">
                Too many failed attempts. Please sign in with your password.
              </p>
            )}

            {/* Divider */}
            <div className="flex items-center gap-3 my-5">
              <div className="flex-1 h-px bg-[var(--forge-border)]" />
              <span className="text-xs text-[var(--forge-text-muted)]">
                or use password
              </span>
              <div className="flex-1 h-px bg-[var(--forge-border)]" />
            </div>
          </div>
        )}

        {/* Email + password form */}
        <form onSubmit={handlePasswordLogin} className="space-y-4">
          {/* Email */}
          <div>
            <label className="block text-xs font-medium text-[var(--forge-text-muted)] mb-1.5">
              Email
            </label>
            <div className="relative">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--forge-text-muted)]" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                disabled={isLoading}
                autoComplete="email"
                className={cn(
                  "w-full pl-11 pr-4 py-3 rounded-xl text-sm outline-none transition-colors",
                  "bg-[var(--forge-channel)] text-[var(--forge-text)]",
                  "border border-[var(--forge-border)]",
                  "focus:border-[var(--forge-accent)]",
                  "placeholder:text-[var(--forge-text-muted)]",
                )}
              />
            </div>
          </div>

          {/* Password */}
          <div>
            <label className="block text-xs font-medium text-[var(--forge-text-muted)] mb-1.5">
              Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--forge-text-muted)]" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                disabled={isLoading}
                autoComplete="current-password"
                className={cn(
                  "w-full pl-11 pr-4 py-3 rounded-xl text-sm outline-none transition-colors",
                  "bg-[var(--forge-channel)] text-[var(--forge-text)]",
                  "border border-[var(--forge-border)]",
                  "focus:border-[var(--forge-accent)]",
                  "placeholder:text-[var(--forge-text-muted)]",
                )}
              />
            </div>
          </div>

          {/* Error */}
          {connectionError && (
            <div className="flex items-start gap-2 text-xs p-3 rounded-xl bg-[var(--forge-error)]/10 text-[var(--forge-error)]">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{connectionError}</span>
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={isLoading || !email.trim() || !password}
            className={cn(
              "w-full flex items-center justify-center gap-2 py-3.5 rounded-xl",
              "text-sm font-medium text-white transition-opacity",
              "bg-[var(--forge-accent)] active:opacity-80",
              "disabled:opacity-50",
              "min-h-[48px]",
            )}
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Signing in...
              </>
            ) : (
              <>
                Sign in
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>
      </div>

      {/* Bottom safe area */}
      <div className="shrink-0 pb-[env(safe-area-inset-bottom)]" />
    </div>
  );
}
