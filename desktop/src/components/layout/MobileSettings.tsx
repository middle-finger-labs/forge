import { useCallback } from "react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import type { NotificationLevel } from "@/stores/settingsStore";
import {
  useBiometricAuth,
  biometryDisplayName,
} from "@/hooks/useBiometricAuth";
import { clearSecureSession } from "@/lib/secureStorage";
import {
  Bell,
  Moon,
  Sun,
  Monitor,
  LogOut,
  Server,
  ScanFace,
  Fingerprint,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Component ──────────────────────────────────────

export function MobileSettings() {
  const { user, org, serverUrl, authToken, logout } = useConnectionStore();
  const {
    theme, setTheme,
    notificationLevel, setNotificationLevel,
    biometricEnabled, setBiometricEnabled,
  } = useSettingsStore();
  const biometric = useBiometricAuth();

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="px-4 pt-[env(safe-area-inset-top)] shrink-0">
        <div className="pt-3 pb-2">
          <h1 className="text-xl font-bold text-white">Settings</h1>
        </div>
      </div>

      {/* User info */}
      <div className="mx-4 mt-2 mb-4 p-4 rounded-xl bg-[var(--forge-sidebar)]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-[var(--forge-accent)] flex items-center justify-center text-white font-bold">
            {user?.name?.[0]?.toUpperCase() ?? "U"}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-white truncate">
              {user?.name ?? "User"}
            </p>
            <p className="text-xs text-[var(--forge-text-muted)] truncate">
              {org?.name ?? "Organization"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 mt-3 text-xs text-[var(--forge-text-muted)]">
          <Server className="w-3 h-3" />
          <span className="truncate">{serverUrl || "Not connected"}</span>
        </div>
      </div>

      {/* Appearance */}
      <SettingsSection label="Appearance">
        <div className="flex items-center gap-2 px-4 py-3">
          <span className="text-sm text-[var(--forge-text)] flex-1">Theme</span>
          <div className="flex items-center gap-1 bg-[var(--forge-hover)] rounded-lg p-0.5">
            <ThemeButton
              icon={Sun}
              active={theme === "light"}
              onPress={() => setTheme("light")}
            />
            <ThemeButton
              icon={Moon}
              active={theme === "dark"}
              onPress={() => setTheme("dark")}
            />
            <ThemeButton
              icon={Monitor}
              active={theme === "system"}
              onPress={() => setTheme("system")}
            />
          </div>
        </div>
      </SettingsSection>

      {/* Notifications */}
      <SettingsSection label="Notifications">
        {NOTIFICATION_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setNotificationLevel(opt.value)}
            className="flex items-center gap-3 w-full px-4 py-3 text-left active:bg-[var(--forge-hover)] transition-colors"
          >
            <Bell className="w-4 h-4 text-[var(--forge-text-muted)]" />
            <span className="text-sm text-[var(--forge-text)] flex-1">{opt.label}</span>
            <div
              className={cn(
                "w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors",
                notificationLevel === opt.value
                  ? "border-[var(--forge-accent)] bg-[var(--forge-accent)]"
                  : "border-[var(--forge-text-muted)]"
              )}
            >
              {notificationLevel === opt.value && (
                <div className="w-2 h-2 rounded-full bg-white" />
              )}
            </div>
          </button>
        ))}
      </SettingsSection>

      {/* Security — only show if biometric hardware is available */}
      {biometric.available && (
        <SettingsSection label="Security">
          <BiometricToggle
            biometric={biometric}
            enabled={biometricEnabled}
            onToggle={setBiometricEnabled}
            user={user}
            org={org}
            serverUrl={serverUrl}
            authToken={authToken}
          />
        </SettingsSection>
      )}

      {/* Account */}
      <SettingsSection label="Account">
        <button
          onClick={() => {
            // Clear biometric session on logout
            if (biometricEnabled) {
              clearSecureSession();
              setBiometricEnabled(false);
            }
            logout();
          }}
          className="flex items-center gap-3 w-full px-4 py-3 text-left active:bg-[var(--forge-hover)] transition-colors"
        >
          <LogOut className="w-4 h-4 text-[var(--forge-error)]" />
          <span className="text-sm text-[var(--forge-error)]">Sign Out</span>
        </button>
      </SettingsSection>

      {/* Version info */}
      <div className="px-4 py-6 mt-auto text-center">
        <p className="text-[11px] text-[var(--forge-text-muted)]">
          Forge v0.1.0
        </p>
        <p className="text-[10px] text-[var(--forge-text-muted)] mt-0.5">
          Middle Finger Labs
        </p>
      </div>
    </div>
  );
}

// ─── Settings Section ───────────────────────────────

function SettingsSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2">
      <div className="px-4 py-2">
        <span className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          {label}
        </span>
      </div>
      <div className="mx-4 rounded-xl bg-[var(--forge-sidebar)] overflow-hidden">
        {children}
      </div>
    </div>
  );
}

// ─── Theme Button ───────────────────────────────────

function ThemeButton({
  icon: Icon,
  active,
  onPress,
}: {
  icon: typeof Sun;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <button
      onClick={onPress}
      className={cn(
        "p-1.5 rounded-md transition-colors",
        active
          ? "bg-[var(--forge-accent)] text-white"
          : "text-[var(--forge-text-muted)]"
      )}
    >
      <Icon className="w-4 h-4" />
    </button>
  );
}

// ─── Biometric Toggle ──────────────────────────────

function BiometricToggle({
  biometric,
  enabled,
  onToggle,
  user,
  org,
  serverUrl,
  authToken,
}: {
  biometric: ReturnType<typeof useBiometricAuth>;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  user: { id: string; email: string; name: string } | null;
  org: { id: string; name: string } | null;
  serverUrl: string;
  authToken: string | null;
}) {
  const BiometricIcon =
    biometric.biometryType === "faceId" ? ScanFace : Fingerprint;
  const label = biometryDisplayName(biometric.biometryType);

  const handleToggle = useCallback(async () => {
    if (enabled) {
      // Disable: clear stored session
      biometric.unenroll();
      onToggle(false);
    } else {
      // Enable: prompt biometric, then save session
      if (!user || !org || !authToken) return;
      const success = await biometric.promptBiometric();
      if (success) {
        biometric.enroll({
          authToken,
          serverUrl,
          userId: user.id,
          userEmail: user.email,
          userName: user.name,
          orgId: org.id,
          orgName: org.name,
        });
        onToggle(true);
      }
    }
  }, [enabled, biometric, user, org, authToken, serverUrl, onToggle]);

  return (
    <button
      onClick={handleToggle}
      className="flex items-center gap-3 w-full px-4 py-3 text-left active:bg-[var(--forge-hover)] transition-colors"
    >
      <BiometricIcon className="w-4 h-4 text-[var(--forge-text-muted)]" />
      <span className="text-sm text-[var(--forge-text)] flex-1">{label}</span>
      <div
        className={cn(
          "w-11 h-6 rounded-full relative transition-colors",
          enabled ? "bg-[var(--forge-accent)]" : "bg-[var(--forge-border)]"
        )}
      >
        <div
          className={cn(
            "absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform",
            enabled ? "translate-x-[22px]" : "translate-x-0.5"
          )}
        />
      </div>
    </button>
  );
}

// ─── Notification options ───────────────────────────

const NOTIFICATION_OPTIONS: Array<{ value: NotificationLevel; label: string }> = [
  { value: "all", label: "All notifications" },
  { value: "approvals", label: "Approvals only" },
  { value: "errors", label: "Errors only" },
  { value: "none", label: "None" },
];
