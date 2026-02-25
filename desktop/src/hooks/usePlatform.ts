import { useState, useEffect } from "react";
import { platform, type Platform } from "@tauri-apps/plugin-os";

interface PlatformInfo {
  isMobile: boolean;
  isDesktop: boolean;
  isIOS: boolean;
  isAndroid: boolean;
  os: Platform;
}

let cachedPlatform: Platform | null = null;

export function usePlatform(): PlatformInfo {
  const [os, setOs] = useState<Platform>(() => cachedPlatform ?? "macos");

  useEffect(() => {
    if (!cachedPlatform) {
      try {
        const detected = platform();
        cachedPlatform = detected;
        setOs(detected);
      } catch {
        // Fallback: infer from user agent during development
        const ua = navigator.userAgent.toLowerCase();
        if (ua.includes("iphone") || ua.includes("ipad")) {
          cachedPlatform = "ios";
        } else if (ua.includes("android")) {
          cachedPlatform = "android";
        } else {
          cachedPlatform = "macos";
        }
        setOs(cachedPlatform);
      }
    }
  }, []);

  return {
    isMobile: os === "ios" || os === "android",
    isDesktop: os === "macos" || os === "windows" || os === "linux",
    isIOS: os === "ios",
    isAndroid: os === "android",
    os,
  };
}
