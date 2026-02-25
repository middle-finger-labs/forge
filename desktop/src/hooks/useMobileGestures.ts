import { useRef, useCallback, useEffect, type RefObject } from "react";

interface SwipeHandlers {
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  onSwipeUp?: () => void;
  onSwipeDown?: () => void;
}

interface LongPressOptions {
  onLongPress: (e: TouchEvent) => void;
  delay?: number;
}

const SWIPE_THRESHOLD = 50;
const SWIPE_VELOCITY_THRESHOLD = 0.3;

/**
 * Hook for swipe gesture detection on a container element.
 * Attaches touch listeners to the given ref.
 */
export function useSwipeGesture(
  ref: RefObject<HTMLElement | null>,
  handlers: SwipeHandlers
) {
  const startX = useRef(0);
  const startY = useRef(0);
  const startTime = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onTouchStart = (e: TouchEvent) => {
      const touch = e.touches[0];
      startX.current = touch.clientX;
      startY.current = touch.clientY;
      startTime.current = Date.now();
    };

    const onTouchEnd = (e: TouchEvent) => {
      const touch = e.changedTouches[0];
      const dx = touch.clientX - startX.current;
      const dy = touch.clientY - startY.current;
      const dt = Date.now() - startTime.current;
      const velocity = Math.abs(dx) / dt;

      // Must meet minimum distance and velocity
      if (Math.abs(dx) < SWIPE_THRESHOLD && Math.abs(dy) < SWIPE_THRESHOLD) return;
      if (velocity < SWIPE_VELOCITY_THRESHOLD && dt > 500) return;

      // Determine direction (horizontal takes priority if larger)
      if (Math.abs(dx) > Math.abs(dy)) {
        if (dx > 0) handlers.onSwipeRight?.();
        else handlers.onSwipeLeft?.();
      } else {
        if (dy > 0) handlers.onSwipeDown?.();
        else handlers.onSwipeUp?.();
      }
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchend", onTouchEnd);
    };
  }, [ref, handlers]);
}

/**
 * Hook for edge-swipe back navigation (swipe right from left 20px).
 */
export function useEdgeSwipeBack(onBack: () => void) {
  useEffect(() => {
    let startX = 0;
    let startY = 0;
    let isEdgeSwipe = false;

    const onTouchStart = (e: TouchEvent) => {
      const touch = e.touches[0];
      startX = touch.clientX;
      startY = touch.clientY;
      // Only trigger if starting from the left edge (first 20px)
      isEdgeSwipe = touch.clientX < 20;
    };

    const onTouchEnd = (e: TouchEvent) => {
      if (!isEdgeSwipe) return;

      const touch = e.changedTouches[0];
      const dx = touch.clientX - startX;
      const dy = Math.abs(touch.clientY - startY);

      // Horizontal swipe right, not too vertical
      if (dx > 80 && dy < 100) {
        onBack();
      }
      isEdgeSwipe = false;
    };

    document.addEventListener("touchstart", onTouchStart, { passive: true });
    document.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      document.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("touchend", onTouchEnd);
    };
  }, [onBack]);
}

/**
 * Hook for long-press gesture detection.
 */
export function useLongPress(
  ref: RefObject<HTMLElement | null>,
  { onLongPress, delay = 500 }: LongPressOptions
) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onTouchStart = (e: TouchEvent) => {
      timerRef.current = setTimeout(() => {
        onLongPress(e);
      }, delay);
    };

    const onTouchEnd = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const onTouchMove = () => {
      // Cancel long press if finger moves
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("touchmove", onTouchMove);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [ref, onLongPress, delay]);
}

/**
 * Hook for pull-to-refresh gesture.
 */
export function usePullToRefresh(
  ref: RefObject<HTMLElement | null>,
  onRefresh: () => Promise<void> | void
) {
  const isRefreshing = useRef(false);
  const pullStartY = useRef(0);

  const handleRefresh = useCallback(async () => {
    if (isRefreshing.current) return;
    isRefreshing.current = true;
    try {
      await onRefresh();
    } finally {
      isRefreshing.current = false;
    }
  }, [onRefresh]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onTouchStart = (e: TouchEvent) => {
      if (el.scrollTop === 0) {
        pullStartY.current = e.touches[0].clientY;
      } else {
        pullStartY.current = 0;
      }
    };

    const onTouchEnd = (e: TouchEvent) => {
      if (pullStartY.current === 0) return;

      const dy = e.changedTouches[0].clientY - pullStartY.current;
      if (dy > 80 && el.scrollTop === 0) {
        handleRefresh();
      }
      pullStartY.current = 0;
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchend", onTouchEnd);
    };
  }, [ref, handleRefresh]);
}
