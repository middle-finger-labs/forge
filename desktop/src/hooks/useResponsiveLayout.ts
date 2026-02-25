import { useState, useEffect } from "react";
import { usePlatform } from "./usePlatform";

export type LayoutMode = "desktop" | "tablet" | "mobile";

interface ResponsiveLayout {
  mode: LayoutMode;
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  width: number;
}

export function useResponsiveLayout(): ResponsiveLayout {
  const { isMobile: isMobilePlatform } = usePlatform();
  const [width, setWidth] = useState(window.innerWidth);

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // On mobile platforms, always use mobile layout regardless of screen size
  // On desktop platforms, allow responsive switching for testing
  const mode: LayoutMode = isMobilePlatform
    ? "mobile"
    : width > 1024
      ? "desktop"
      : width > 768
        ? "tablet"
        : "mobile";

  return {
    mode,
    isMobile: mode === "mobile",
    isTablet: mode === "tablet",
    isDesktop: mode === "desktop",
    width,
  };
}
