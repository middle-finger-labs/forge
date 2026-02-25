import { useEffect } from "react";
import { useOnboardingStore } from "@/stores/onboardingStore";
import { useConnectionStore } from "@/stores/connectionStore";

/**
 * Fetches onboarding state on app load once authenticated.
 * Returns derived helpers for checking onboarding visibility.
 */
export function useOnboarding() {
  const { serverUrl, authToken, connectionStatus } = useConnectionStore();
  const {
    loaded,
    loading,
    fetchState,
    shouldShowOnboarding,
    shouldShowBanner,
    completedCount,
    totalSteps,
  } = useOnboardingStore();

  useEffect(() => {
    if (
      connectionStatus === "authenticated" &&
      serverUrl &&
      authToken &&
      !loaded &&
      !loading
    ) {
      fetchState(serverUrl, authToken);
    }
  }, [connectionStatus, serverUrl, authToken, loaded, loading, fetchState]);

  return {
    loaded,
    loading,
    showOnboarding: shouldShowOnboarding(),
    showBanner: shouldShowBanner(),
    completedCount: completedCount(),
    totalSteps: totalSteps(),
  };
}
