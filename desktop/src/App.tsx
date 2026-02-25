import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ConnectScreen } from "@/components/ConnectScreen";
import { BiometricEnrollSheet } from "@/components/auth/BiometricEnrollSheet";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useResponsiveLayout } from "@/hooks/useResponsiveLayout";
import { useBiometricAuth } from "@/hooks/useBiometricAuth";
import { useAuthDeepLink } from "@/hooks/useAuthDeepLink";
import { Loader2, Wifi } from "lucide-react";

function App() {
  const { connectionStatus, restoreSession, initializeAuth, serverUrl, authToken } =
    useConnectionStore();
  const { biometricEnabled, biometricPromptShown } = useSettingsStore();
  const { isMobile } = useResponsiveLayout();
  const biometric = useBiometricAuth();

  // Listen for forge://auth deep links (magic link flow)
  useAuthDeepLink();

  const [showEnrollSheet, setShowEnrollSheet] = useState(false);
  const [isRestoring, setIsRestoring] = useState(!!serverUrl && !!authToken);

  // Initialize auth from keyring, then attempt session restore
  useEffect(() => {
    async function init() {
      await initializeAuth();
      const { serverUrl: sUrl, authToken: aToken } = useConnectionStore.getState();
      if (sUrl && aToken) {
        setIsRestoring(true);
        await restoreSession().finally(() => setIsRestoring(false));
      } else {
        setIsRestoring(false);
      }
    }
    init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Show biometric enrollment prompt after first login on mobile
  // (only if biometric is available and we haven't shown the prompt yet)
  useEffect(() => {
    if (
      isMobile &&
      connectionStatus === "authenticated" &&
      biometric.available &&
      !biometricEnabled &&
      !biometricPromptShown
    ) {
      // Small delay to let the app settle after login
      const timer = setTimeout(() => setShowEnrollSheet(true), 800);
      return () => clearTimeout(timer);
    }
  }, [
    isMobile,
    connectionStatus,
    biometric.available,
    biometricEnabled,
    biometricPromptShown,
  ]);

  // Splash screen during session restore
  if (isRestoring) {
    return (
      <div
        className="h-screen flex flex-col items-center justify-center gap-4"
        style={{ background: "var(--forge-bg)" }}
      >
        <div
          className="inline-flex items-center justify-center w-16 h-16 rounded-2xl"
          style={{ background: "var(--forge-accent)", opacity: 0.9 }}
        >
          <Wifi className="w-8 h-8 text-white" />
        </div>
        <Loader2
          className="w-6 h-6 animate-spin"
          style={{ color: "var(--forge-text-muted)" }}
        />
      </div>
    );
  }

  // Route based on connection state
  if (connectionStatus === "unconfigured" || connectionStatus === "awaiting_magic_link") {
    return <ConnectScreen />;
  }

  if (
    connectionStatus === "connected" ||
    (connectionStatus === "error" && !authToken)
  ) {
    // Show magic link email entry (ConnectScreen handles both states)
    return <ConnectScreen />;
  }

  if (connectionStatus === "authenticated") {
    return (
      <>
        <AppShell />
        {showEnrollSheet && (
          <BiometricEnrollSheet onClose={() => setShowEnrollSheet(false)} />
        )}
      </>
    );
  }

  // connecting / disconnected with token — show AppShell (will reconnect)
  if (authToken) {
    return <AppShell />;
  }

  // Fallback: no token, show connect screen
  return <ConnectScreen />;
}

export default App;
