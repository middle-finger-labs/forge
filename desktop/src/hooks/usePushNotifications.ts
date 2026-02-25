import { useEffect, useRef, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { usePlatform } from "./usePlatform";
import { useConnectionStore } from "@/stores/connectionStore";

// ─── Types ───────────────────────────────────────────

interface DeepLinkPayload {
  type: "pipeline" | "approval" | "dm";
  url: string;
  pipeline_id?: string;
  stage?: string;
  agent_role?: string;
}

// ─── Hook ────────────────────────────────────────────

/**
 * Manages push notification registration and deep-link handling on mobile.
 *
 * On mount (mobile only):
 * 1. Listens for the native push token via the JS bridge (`window.__FORGE_PUSH_TOKEN`)
 * 2. Stores the token in Rust state via the `set_push_token` command
 * 3. Registers the token with the backend API (`POST /api/push/register`)
 * 4. Listens for notification taps and routes deep links
 *
 * On logout:
 * - Unregisters the token from the backend (`DELETE /api/push/unregister`)
 *
 * @param onDeepLink - Callback invoked when the user taps a push notification.
 *   Receives a parsed deep-link payload for navigation routing.
 */
export function usePushNotifications(
  onDeepLink?: (payload: DeepLinkPayload) => void,
) {
  const { isMobile, isIOS, isAndroid } = usePlatform();
  const { serverUrl, authToken, user } = useConnectionStore();
  const tokenRef = useRef<string | null>(null);
  const registeredRef = useRef(false);
  const onDeepLinkRef = useRef(onDeepLink);
  onDeepLinkRef.current = onDeepLink;

  // ── Register token with backend ──────────────────

  const registerWithBackend = useCallback(
    async (token: string) => {
      if (!serverUrl || !authToken || registeredRef.current) return;

      try {
        const platform = isIOS ? "ios" : "android";
        const res = await fetch(`${serverUrl}/api/push/register`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify({
            platform,
            token,
            device_name: user?.name ?? undefined,
            app_version: "0.1.0",
          }),
        });

        if (res.ok) {
          registeredRef.current = true;
          console.log("[Push] Token registered with backend");
        } else {
          console.warn("[Push] Backend registration failed:", res.status);
        }
      } catch (err) {
        console.warn("[Push] Backend registration error:", err);
      }
    },
    [serverUrl, authToken, isIOS, user?.name],
  );

  // ── Unregister token from backend ────────────────

  const unregisterFromBackend = useCallback(async () => {
    const token = tokenRef.current;
    if (!token || !serverUrl || !authToken) return;

    try {
      await fetch(`${serverUrl}/api/push/unregister`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ token }),
      });
      registeredRef.current = false;
      console.log("[Push] Token unregistered from backend");
    } catch {
      // Best-effort cleanup
    }
  }, [serverUrl, authToken]);

  // ── iOS: listen for APNs token via JS bridge ─────

  useEffect(() => {
    if (!isMobile || !isIOS) return;

    const handleToken = async (token: string) => {
      console.log("[Push] iOS token received:", token.slice(0, 16) + "...");
      tokenRef.current = token;

      // Store in Rust state
      try {
        await invoke("set_push_token", { token });
      } catch {
        // Non-critical — the JS layer manages registration
      }

      // Register with backend
      await registerWithBackend(token);
    };

    const handleError = (error: string) => {
      console.warn("[Push] iOS registration error:", error);
    };

    // Set up the bridge callbacks that ForgePush.swift will call
    (window as any).__FORGE_PUSH_TOKEN = handleToken;
    (window as any).__FORGE_PUSH_ERROR = handleError;

    // If the token was already received before this hook mounted,
    // check if Rust has it stored
    invoke<string | null>("get_push_token").then((existingToken) => {
      if (existingToken && !tokenRef.current) {
        handleToken(existingToken);
      }
    }).catch(() => {});

    return () => {
      delete (window as any).__FORGE_PUSH_TOKEN;
      delete (window as any).__FORGE_PUSH_ERROR;
    };
  }, [isMobile, isIOS, registerWithBackend]);

  // ── Android: read FCM token from SharedPreferences bridge ─

  useEffect(() => {
    if (!isMobile || !isAndroid) return;

    // On Android, the FCM token is stored by ForgeFCMService in SharedPreferences.
    // We poll for it on mount since there's no direct callback mechanism.
    // In production, this would use a Tauri plugin or custom Kotlin bridge.
    const checkToken = async () => {
      try {
        const token = await invoke<string | null>("get_push_token");
        if (token && !tokenRef.current) {
          tokenRef.current = token;
          await registerWithBackend(token);
        }
      } catch {
        // Token not yet available
      }
    };

    checkToken();

    // Re-check periodically in case the token arrives late
    const interval = setInterval(checkToken, 5000);
    return () => clearInterval(interval);
  }, [isMobile, isAndroid, registerWithBackend]);

  // ── Deep link handler ────────────────────────────

  useEffect(() => {
    if (!isMobile) return;

    const handleDeepLink = (urlString: string) => {
      console.log("[Push] Deep link received:", urlString);

      const payload = parseDeepLink(urlString);
      if (payload) {
        onDeepLinkRef.current?.(payload);
      }
    };

    // iOS: ForgePush.swift calls this when a notification is tapped
    (window as any).__FORGE_DEEP_LINK = handleDeepLink;

    // Also listen for the Tauri deep-link plugin events (handles both platforms)
    let unlisten: (() => void) | null = null;

    import("@tauri-apps/plugin-deep-link").then((deepLink) => {
      deepLink.onOpenUrl((urls) => {
        for (const url of urls) {
          handleDeepLink(url);
        }
      }).then((fn) => {
        unlisten = fn;
      }).catch(() => {});
    }).catch(() => {});

    return () => {
      delete (window as any).__FORGE_DEEP_LINK;
      unlisten?.();
    };
  }, [isMobile]);

  // ── Re-register when auth state changes ──────────

  useEffect(() => {
    if (!isMobile || !authToken || !tokenRef.current) return;
    registerWithBackend(tokenRef.current);
  }, [isMobile, authToken, registerWithBackend]);

  return {
    unregister: unregisterFromBackend,
    token: tokenRef.current,
  };
}

// ─── Deep link parser ────────────────────────────────

/**
 * Parse a `forge://` deep-link URL into a typed payload.
 *
 * Supported patterns:
 * - `forge://pipeline/{id}` → open pipeline channel
 * - `forge://approve/{pipeline_id}/{stage}` → open approval card
 * - `forge://dm/{agent_role}` → open agent DM
 */
function parseDeepLink(urlString: string): DeepLinkPayload | null {
  try {
    // forge://pipeline/abc-123
    // forge://approve/abc-123/engineer
    // forge://dm/engineer
    const url = new URL(urlString);

    if (url.protocol !== "forge:") return null;

    // URL parsing: forge://pipeline/abc-123
    // host = "pipeline", pathname = "/abc-123"
    const host = url.host || url.hostname;
    const pathParts = url.pathname.split("/").filter(Boolean);

    switch (host) {
      case "pipeline":
        return {
          type: "pipeline",
          url: urlString,
          pipeline_id: pathParts[0],
        };

      case "approve":
        return {
          type: "approval",
          url: urlString,
          pipeline_id: pathParts[0],
          stage: pathParts[1],
        };

      case "dm":
        return {
          type: "dm",
          url: urlString,
          agent_role: pathParts[0],
        };

      default:
        console.warn("[Push] Unknown deep link type:", host);
        return null;
    }
  } catch {
    console.warn("[Push] Failed to parse deep link:", urlString);
    return null;
  }
}
