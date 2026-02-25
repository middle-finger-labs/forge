import { useState, useCallback, useRef, type RefObject } from "react";

// ─── Types ──────────────────────────────────────────

interface CollapsibleHeaderState {
  /** 0 = fully expanded, 1 = fully collapsed */
  progress: number;
  /** Whether the large title is fully collapsed */
  collapsed: boolean;
  /** Attach to the scrollable container */
  scrollRef: RefObject<HTMLDivElement | null>;
  /** Call on scroll events */
  onScroll: () => void;
}

// ─── Constants ──────────────────────────────────────

const COLLAPSE_THRESHOLD = 48; // px of scroll before fully collapsed

// ─── Hook ───────────────────────────────────────────

/**
 * iOS-style large title navigation header that collapses on scroll.
 * Returns a progress value (0–1) and scroll handler.
 */
export function useCollapsibleHeader(): CollapsibleHeaderState {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [progress, setProgress] = useState(0);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const scrollTop = el.scrollTop;
    const p = Math.min(scrollTop / COLLAPSE_THRESHOLD, 1);
    setProgress(p);
  }, []);

  return {
    progress,
    collapsed: progress >= 0.95,
    scrollRef,
    onScroll,
  };
}
