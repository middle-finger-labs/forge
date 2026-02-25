import { useEffect } from "react";
import { useConnectionStore } from "@/stores/connectionStore";

/**
 * Listens for `forge://auth?token=...&server=...` deep links on all platforms.
 *
 * When a magic link is tapped (from email), the OS opens the app with the
 * forge:// URL. This hook intercepts it and calls `verifyMagicLink` to
 * complete the passwordless authentication flow.
 */
export function useAuthDeepLink() {
  const { verifyMagicLink } = useConnectionStore();

  useEffect(() => {
    let unlisten: (() => void) | null = null;

    const handleUrl = async (urlString: string) => {
      try {
        const url = new URL(urlString);
        if (url.protocol !== "forge:") return;

        const host = url.host || url.hostname;
        if (host !== "auth") return;

        const token = url.searchParams.get("token");
        const server = url.searchParams.get("server");

        if (!token) {
          console.warn("[Auth] Deep link missing token:", urlString);
          return;
        }

        console.log("[Auth] Magic link received, verifying...");
        await verifyMagicLink(token, server || undefined);
      } catch (err) {
        console.error("[Auth] Deep link handling failed:", err);
      }
    };

    // Listen via Tauri deep-link plugin (works on desktop + mobile)
    import("@tauri-apps/plugin-deep-link").then((deepLink) => {
      deepLink.onOpenUrl((urls) => {
        for (const url of urls) {
          handleUrl(url);
        }
      }).then((fn) => {
        unlisten = fn;
      }).catch(() => {});
    }).catch(() => {});

    // Also expose on window for native bridges (iOS/Android)
    (window as any).__FORGE_AUTH_DEEP_LINK = handleUrl;

    return () => {
      unlisten?.();
      delete (window as any).__FORGE_AUTH_DEEP_LINK;
    };
  }, [verifyMagicLink]);
}
