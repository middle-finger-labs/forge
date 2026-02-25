import { useEffect } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ConnectScreen } from "@/components/ConnectScreen";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { useConnectionStore } from "@/stores/connectionStore";

function App() {
  const { connectionStatus, restoreSession, serverUrl, authToken } =
    useConnectionStore();

  // Attempt session restore on mount
  useEffect(() => {
    if (serverUrl && authToken) {
      restoreSession();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Route based on connection state
  if (connectionStatus === "unconfigured") {
    return <ConnectScreen />;
  }

  if (
    connectionStatus === "connected" ||
    (connectionStatus === "error" && !authToken)
  ) {
    return <LoginScreen />;
  }

  if (connectionStatus === "authenticated") {
    return <AppShell />;
  }

  // connecting / disconnected with token — show AppShell (will reconnect)
  if (authToken) {
    return <AppShell />;
  }

  // Fallback: no token, show connect screen
  return <ConnectScreen />;
}

export default App;
