import { useCallback, useEffect, useRef, useState } from 'react'
import type { PresenceUser } from './useWebSocket.ts'

const AWAY_TIMEOUT_MS = 3 * 60 * 1000 // 3 minutes of inactivity → "away"
const ACTIVITY_EVENTS = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll']

interface UsePresenceReturn {
  /** List of online users in the room, enriched with "away" status. */
  users: PresenceUser[]
  /** Whether the current user is marked as away. */
  isAway: boolean
}

/**
 * Track presence state for the current pipeline room.
 *
 * Listens for user activity (mouse, keyboard) and sends presence updates
 * via the WebSocket `send` callback when the user goes idle or returns.
 *
 * @param online - The online users array from useWebSocket
 * @param send - The send function from useWebSocket
 * @param currentUserId - The current user's ID (to detect own away state)
 */
export function usePresence(
  online: PresenceUser[],
  send: (msg: Record<string, unknown>) => void,
  _currentUserId: string | undefined,
): UsePresenceReturn {
  const [isAway, setIsAway] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isAwayRef = useRef(false)

  const resetTimer = useCallback(() => {
    if (isAwayRef.current) {
      // Coming back from away
      isAwayRef.current = false
      setIsAway(false)
      send({ type: 'presence_update', status: 'online' })
    }

    if (timerRef.current) {
      clearTimeout(timerRef.current)
    }

    timerRef.current = setTimeout(() => {
      isAwayRef.current = true
      setIsAway(true)
      send({ type: 'presence_update', status: 'away' })
    }, AWAY_TIMEOUT_MS)
  }, [send])

  useEffect(() => {
    // Set initial timer
    resetTimer()

    // Listen for activity events
    for (const event of ACTIVITY_EVENTS) {
      document.addEventListener(event, resetTimer, { passive: true })
    }

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      for (const event of ACTIVITY_EVENTS) {
        document.removeEventListener(event, resetTimer)
      }
    }
  }, [resetTimer])

  return {
    users: online,
    isAway,
  }
}
