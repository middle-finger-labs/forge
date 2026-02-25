import { useEffect, useState, useCallback } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ConnectScreen } from "@/components/ConnectScreen";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { MobileLoginScreen } from "@/components/auth/MobileLoginScreen";
import { BiometricEnrollSheet } from "@/components/auth/BiometricEnrollSheet";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useResponsiveLayout } from "@/hooks/useResponsiveLayout";
import { useBiometricAuth } from "@/hooks/useBiometricAuth";

function App() {
  const { connectionStatus, restoreSession, serverUrl, authToken, setConnectionStatus } =
    useConnectionStore();
  const { biometricEnabled, biometricPromptShown } = useSettingsStore();
  const { isMobile } = useResponsiveLayout();
  const biometric = useBiometricAuth();

  const [showEnrollSheet, setShowEnrollSheet] = useState(false);

  // Attempt session restore on mount
  useEffect(() => {
    if (serverUrl && authToken) {
      restoreSession();
    }
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

  // Mobile server config: go back to unconfigured
  const handleOpenServerConfig = useCallback(() => {
    setConnectionStatus("unconfigured");
  }, [setConnectionStatus]);

  // Route based on connection state
  if (connectionStatus === "unconfigured") {
    return <ConnectScreen />;
  }

  if (
    connectionStatus === "connected" ||
    (connectionStatus === "error" && !authToken)
  ) {
    // Mobile gets a dedicated login screen with biometric support
    if (isMobile) {
      return <MobileLoginScreen onOpenServerConfig={handleOpenServerConfig} />;
    }
    return <LoginScreen />;
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
