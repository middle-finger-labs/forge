import { useCallback, useEffect, useRef, useState } from 'react'
import type { AgentEvent } from '../types/pipeline.ts'

const WS_BASE = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'
const FLUSH_INTERVAL_MS = 100
const MAX_BACKOFF_MS = 30_000
const INITIAL_BACKOFF_MS = 500
const HEARTBEAT_INTERVAL_MS = 60_000

// ---------------------------------------------------------------------------
// Multiplayer message types
// ---------------------------------------------------------------------------

export interface PresenceUser {
  user_id: string
  user_name: string
  email: string
  status?: string
  joined_at?: string
}

export interface ChatMessage {
  id: string
  pipeline_id: string
  user_id: string
  user_name: string
  content: string
  message_type: string
  created_at: string
}

export interface TypingState {
  user_id: string
  user_name: string
  is_typing: boolean
}

export type WsMessage =
  | { type: 'user_joined'; user: PresenceUser; online: PresenceUser[] }
  | { type: 'user_left'; user_id: string; online: PresenceUser[] }
  | { type: 'presence_sync'; online: PresenceUser[] }
  | { type: 'typing'; user_id: string; user_name: string; is_typing: boolean }
  | { type: 'chat_message'; message: ChatMessage }
  | AgentEvent // pipeline events (no "type" field with these specific values)

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface UseWebSocketReturn {
  events: AgentEvent[]
  connected: boolean
  error: string | null
  online: PresenceUser[]
  chatMessages: ChatMessage[]
  typingUsers: TypingState[]
  send: (msg: Record<string, unknown>) => void
}

/**
 * Connect to the multiplayer pipeline WebSocket endpoint.
 *
 * Handles:
 * - Pipeline event streaming (buffered flushes)
 * - Presence tracking (user_joined/user_left/presence_sync)
 * - Typing indicators
 * - Chat messages broadcast via room pub/sub
 * - Heartbeat for presence TTL refresh
 * - Token-based authentication via query param
 */
export function useWebSocket(pipelineId: string | undefined): UseWebSocketReturn {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [online, setOnline] = useState<PresenceUser[]>([])
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [typingUsers, setTypingUsers] = useState<TypingState[]>([])

  // Mutable buffer for incoming pipeline events between flushes
  const bufferRef = useRef<AgentEvent[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(INITIAL_BACKOFF_MS)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const unmountedRef = useRef(false)

  const flush = useCallback(() => {
    if (bufferRef.current.length === 0) return
    const batch = bufferRef.current
    bufferRef.current = []
    setEvents((prev) => [...prev, ...batch])
  }, [])

  const send = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  }, [])

  useEffect(() => {
    unmountedRef.current = false

    if (!pipelineId) return

    // Flush timer
    const flushTimer = setInterval(flush, FLUSH_INTERVAL_MS)

    function getSessionToken(): string {
      // Better Auth stores session token in a cookie
      const match = document.cookie.match(/better-auth\.session_token=([^;]+)/)
      return match ? match[1] : ''
    }

    function connect() {
      if (unmountedRef.current) return

      const token = getSessionToken()
      const url = `${WS_BASE}/ws/pipeline/${pipelineId}?token=${encodeURIComponent(token)}`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (unmountedRef.current) return
        setConnected(true)
        setError(null)
        backoffRef.current = INITIAL_BACKOFF_MS

        // Start heartbeat
        heartbeatTimerRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'heartbeat' }))
          }
        }, HEARTBEAT_INTERVAL_MS)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          // Route by message type
          if (data.type === 'user_joined' || data.type === 'user_left' || data.type === 'presence_sync') {
            setOnline(data.online ?? [])
          } else if (data.type === 'typing') {
            setTypingUsers((prev) => {
              const filtered = prev.filter((t) => t.user_id !== data.user_id)
              if (data.is_typing) {
                return [...filtered, { user_id: data.user_id, user_name: data.user_name, is_typing: true }]
              }
              return filtered
            })
          } else if (data.type === 'chat_message') {
            setChatMessages((prev) => [...prev, data.message])
          } else {
            // Pipeline event
            bufferRef.current.push(data as AgentEvent)
          }
        } catch {
          // Ignore malformed messages
        }
      }

      ws.onerror = () => {
        if (unmountedRef.current) return
        setError('WebSocket error')
      }

      ws.onclose = (e) => {
        if (unmountedRef.current) return
        setConnected(false)

        if (heartbeatTimerRef.current) {
          clearInterval(heartbeatTimerRef.current)
          heartbeatTimerRef.current = null
        }

        // Don't reconnect on auth failure
        if (e.code === 4001) {
          setError('Unauthorized — please log in again')
          return
        }

        // Exponential backoff reconnect
        const delay = backoffRef.current
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS)

        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      unmountedRef.current = true
      clearInterval(flushTimer)

      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current)
      }

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }

      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [pipelineId, flush])

  return { events, connected, error, online, chatMessages, typingUsers, send }
}
