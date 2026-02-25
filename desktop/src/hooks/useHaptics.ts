import { useCallback } from "react";
import { usePlatform } from "./usePlatform";

// ─── Types ──────────────────────────────────────────

export type HapticStyle =
  | "light"    // selecting a conversation, tab switch
  | "medium"   // sending a message
  | "heavy"    // approving/rejecting a stage
  | "success"  // pipeline completed
  | "error";   // pipeline failed

// ─── Platform haptics ───────────────────────────────

async function triggerHaptic(style: HapticStyle): Promise<void> {
  try {
    const haptics = await import("@tauri-apps/plugin-haptics");

    switch (style) {
      case "light":
      case "medium":
      case "heavy":
        await haptics.impactFeedback(style as never);
        break;
      case "success":
        await haptics.notificationFeedback("success" as never);
        break;
      case "error":
        await haptics.notificationFeedback("error" as never);
        break;
    }
  } catch {
    // Not available (desktop or plugin not loaded)
  }
}

// ─── Hook ───────────────────────────────────────────

/**
 * Centralized haptic feedback for mobile interactions.
 * Returns a no-op on desktop platforms for zero overhead.
 */
export function useHaptics() {
  const { isMobile } = usePlatform();

  const haptic = useCallback(
    (style: HapticStyle) => {
      if (!isMobile) return;
      triggerHaptic(style);
    },
    [isMobile],
  );

  return { haptic };
}

/**
 * Standalone haptic trigger (for use outside React components).
 * Checks navigator for mobile context.
 */
export async function hapticFeedback(style: HapticStyle): Promise<void> {
  const ua = navigator.userAgent.toLowerCase();
  const isMobile = ua.includes("iphone") || ua.includes("ipad") || ua.includes("android");
  if (!isMobile) return;
  await triggerHaptic(style);
}
