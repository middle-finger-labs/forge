import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Eye,
  MessageSquare,
  Send,
  ShieldAlert,
  Terminal,
  XCircle,
} from 'lucide-react'
import clsx from 'clsx'
import {
  abortPipeline,
  approvePipeline,
  createPipelineMessage,
  getPipelineState,
  listPipelineMessages,
  rejectPipeline,
} from '../lib/api.ts'
import type { AgentEvent, PipelineState } from '../types/pipeline.ts'
import type { ChatMessage as WsChatMessage, TypingState } from '../hooks/useWebSocket.ts'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MessageKind = 'system' | 'human' | 'approval' | 'status' | 'chat'

interface ChatMessage {
  id: string
  kind: MessageKind
  text: string
  detail?: string
  timestamp: string
  variant?: 'success' | 'warning' | 'error' | 'info'
  senderName?: string
  senderId?: string
}

// ---------------------------------------------------------------------------
// Artifact mapping — which spec to show for each approval stage
// ---------------------------------------------------------------------------

const ARTIFACT_FOR_STAGE: Record<string, keyof PipelineState> = {
  business_analysis: 'product_spec',
  research: 'enriched_spec',
  architecture: 'tech_spec',
  task_decomposition: 'prd_board',
}

function stageLabel(stage: string): string {
  return stage.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// ---------------------------------------------------------------------------
// Derive chat messages from events
// ---------------------------------------------------------------------------

const CHAT_EVENT_TYPES = new Set([
  'stage.started',
  'stage.completed',
  'human.approval_required',
  'human.approval_received',
  'human.approval_rejected',
  'pipeline.completed',
  'pipeline.failed',
  'pipeline.aborted',
  'cto.intervention',
])

function eventsToChatMessages(events: AgentEvent[]): ChatMessage[] {
  const msgs: ChatMessage[] = []

  for (const evt of events) {
    if (!CHAT_EVENT_TYPES.has(evt.event_type)) continue

    const ts = evt.timestamp ?? evt.created_at
    const p = evt.payload

    switch (evt.event_type) {
      case 'stage.started':
        msgs.push({
          id: evt.id + '-start',
          kind: 'system',
          text: `${stageLabel(String(evt.stage ?? p.stage ?? '?'))} started`,
          timestamp: ts,
          variant: 'info',
        })
        break

      case 'stage.completed': {
        const dur = p.duration_s != null ? ` in ${Number(p.duration_s).toFixed(1)}s` : ''
        msgs.push({
          id: evt.id + '-done',
          kind: 'system',
          text: `${stageLabel(String(evt.stage ?? p.stage ?? '?'))} completed${dur}`,
          timestamp: ts,
          variant: 'success',
        })
        break
      }

      case 'human.approval_required':
        msgs.push({
          id: evt.id + '-approval',
          kind: 'system',
          text: `Waiting for approval on ${stageLabel(String(evt.stage ?? p.stage ?? '?'))}`,
          timestamp: ts,
          variant: 'warning',
        })
        break

      case 'human.approval_received':
        msgs.push({
          id: evt.id + '-granted',
          kind: 'approval',
          text: `${p.approved_by ?? 'Someone'} approved ${stageLabel(String(evt.stage ?? p.stage ?? '?'))}`,
          detail: p.notes ? String(p.notes) : undefined,
          timestamp: ts,
          variant: 'success',
          senderName: p.approved_by ? String(p.approved_by) : undefined,
        })
        break

      case 'human.approval_rejected':
        msgs.push({
          id: evt.id + '-rejected',
          kind: 'approval',
          text: `${p.rejected_by ?? 'Someone'} rejected ${stageLabel(String(evt.stage ?? p.stage ?? '?'))}`,
          detail: p.notes ? String(p.notes) : undefined,
          timestamp: ts,
          variant: 'error',
          senderName: p.rejected_by ? String(p.rejected_by) : undefined,
        })
        break

      case 'pipeline.completed':
        msgs.push({
          id: evt.id + '-complete',
          kind: 'system',
          text: 'Pipeline completed successfully',
          timestamp: ts,
          variant: 'success',
        })
        break

      case 'pipeline.failed':
        msgs.push({
          id: evt.id + '-failed',
          kind: 'system',
          text: `Pipeline failed: ${p.reason ?? p.error ?? 'unknown error'}`,
          timestamp: ts,
          variant: 'error',
        })
        break

      case 'pipeline.aborted':
        msgs.push({
          id: evt.id + '-aborted',
          kind: 'system',
          text: `Pipeline aborted: ${p.reason ?? 'user requested'}`,
          timestamp: ts,
          variant: 'error',
        })
        break

      case 'cto.intervention':
        msgs.push({
          id: evt.id + '-cto',
          kind: 'system',
          text: `CTO intervention: ${p.trigger ?? p.reason ?? '?'}`,
          timestamp: ts,
          variant: 'warning',
        })
        break
    }
  }

  return msgs
}

// ---------------------------------------------------------------------------
// Convert persistent/WebSocket chat messages to ChatMessage
// ---------------------------------------------------------------------------

function chatMsgToChatMessage(msg: WsChatMessage, currentUserId?: string): ChatMessage {
  return {
    id: `chat-${msg.id}`,
    kind: 'chat',
    text: msg.content,
    timestamp: msg.created_at,
    senderName: msg.user_name,
    senderId: msg.user_id,
    variant: msg.user_id === currentUserId ? undefined : 'info',
  }
}

// ---------------------------------------------------------------------------
// Time formatting
// ---------------------------------------------------------------------------

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// ---------------------------------------------------------------------------
// Approval Card
// ---------------------------------------------------------------------------

function ApprovalCard({
  state,
  pipelineId,
  userName,
  onAction,
  onViewArtifact,
}: {
  state: PipelineState
  pipelineId: string
  userName?: string
  onAction: (msg: ChatMessage) => void
  onViewArtifact?: (stage: string, data: Record<string, unknown>) => void
}) {
  const stage = state.pending_approval!
  const [showArtifact, setShowArtifact] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const artifactKey = ARTIFACT_FOR_STAGE[stage]
  const artifact = artifactKey ? state[artifactKey] : null

  async function handleAction(action: 'approve' | 'reject') {
    setSubmitting(action)
    setError(null)

    const fn = action === 'approve' ? approvePipeline : rejectPipeline
    const name = userName ?? 'You'
    try {
      await fn(pipelineId, { stage, notes: notes || undefined, approved_by: userName })
      onAction({
        id: `local-${Date.now()}`,
        kind: 'approval',
        text: action === 'approve'
          ? `${name} approved ${stageLabel(stage)}`
          : `${name} rejected ${stageLabel(stage)}`,
        detail: notes || undefined,
        timestamp: new Date().toISOString(),
        variant: action === 'approve' ? 'success' : 'error',
        senderName: userName,
      })
      setNotes('')
      setShowNotes(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <div className="mx-2 rounded-xl border border-amber-700/50 bg-amber-950/20 p-4">
      {/* Header */}
      <div className="mb-3 flex items-center gap-2">
        <ShieldAlert className="h-5 w-5 text-amber-400" />
        <h3 className="font-semibold text-amber-200">Approval Required</h3>
      </div>

      <p className="mb-3 text-sm text-slate-300">
        <span className="font-medium text-amber-300">{stageLabel(stage)}</span> has completed and is waiting for your review.
      </p>

      {/* View artifact */}
      {artifact && (
        <div className="mb-3">
          {onViewArtifact ? (
            <button
              onClick={() => onViewArtifact(stage, artifact as Record<string, unknown>)}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
            >
              <Eye className="h-3.5 w-3.5" />
              View Artifact
              <ChevronRight className="h-3 w-3" />
            </button>
          ) : (
            <>
              <button
                onClick={() => setShowArtifact((v) => !v)}
                className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
              >
                <Eye className="h-3.5 w-3.5" />
                View Artifact
                {showArtifact
                  ? <ChevronDown className="h-3 w-3" />
                  : <ChevronRight className="h-3 w-3" />}
              </button>
              {showArtifact && (
                <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-slate-700 bg-[#0c0e14] p-3 font-mono text-[11px] leading-relaxed text-slate-300">
                  {JSON.stringify(artifact, null, 2)}
                </pre>
              )}
            </>
          )}
        </div>
      )}

      {/* Notes toggle */}
      {!showNotes ? (
        <button
          onClick={() => setShowNotes(true)}
          className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
        >
          <MessageSquare className="h-3 w-3" />
          Add notes
        </button>
      ) : (
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional notes for this decision..."
          rows={2}
          className="mb-3 w-full resize-none rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-700 focus:outline-none"
        />
      )}

      {/* Error */}
      {error && (
        <div className="mb-3 rounded-md border border-red-800 bg-red-950/50 px-3 py-1.5 text-xs text-red-300">
          {error}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => handleAction('approve')}
          disabled={submitting !== null}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:opacity-50"
        >
          {submitting === 'approve'
            ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            : <Check className="h-4 w-4" />}
          Approve
        </button>
        <button
          onClick={() => handleAction('reject')}
          disabled={submitting !== null}
          className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-500 disabled:opacity-50"
        >
          {submitting === 'reject'
            ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            : <XCircle className="h-4 w-4" />}
          Reject
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({ msg, isOwnMessage }: { msg: ChatMessage; isOwnMessage?: boolean }) {
  if (msg.kind === 'system' || msg.kind === 'status') {
    const iconMap = {
      success: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
      warning: <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />,
      error: <XCircle className="h-3.5 w-3.5 text-red-500" />,
      info: <Terminal className="h-3.5 w-3.5 text-cyan-500" />,
    }
    const textColor = {
      success: 'text-emerald-300',
      warning: 'text-amber-300',
      error: 'text-red-300',
      info: 'text-slate-400',
    }

    return (
      <div className="flex justify-center px-4 py-1.5">
        <div className="inline-flex max-w-md items-center gap-2 rounded-full bg-slate-800/60 px-3 py-1 text-xs">
          {iconMap[msg.variant ?? 'info']}
          <span className={textColor[msg.variant ?? 'info']}>{msg.text}</span>
          <span className="text-slate-600">{fmtTime(msg.timestamp)}</span>
        </div>
      </div>
    )
  }

  if (msg.kind === 'approval') {
    const iconMap = {
      success: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
      error: <XCircle className="h-3.5 w-3.5 text-red-500" />,
    }
    return (
      <div className="flex justify-center px-4 py-1.5">
        <div className="inline-flex max-w-md items-center gap-2 rounded-full bg-slate-800/60 px-3 py-1 text-xs">
          {iconMap[(msg.variant as 'success' | 'error') ?? 'success']}
          <span className={msg.variant === 'error' ? 'text-red-300' : 'text-emerald-300'}>
            {msg.text}
          </span>
          {msg.detail && (
            <span className="text-slate-500">"{msg.detail}"</span>
          )}
          <span className="text-slate-600">{fmtTime(msg.timestamp)}</span>
        </div>
      </div>
    )
  }

  // Chat / human messages
  if (isOwnMessage) {
    // Own messages — right-aligned
    return (
      <div className="flex justify-end px-4 py-1.5">
        <div className="max-w-xs">
          <div className="rounded-2xl rounded-br-sm bg-cyan-900/40 px-3.5 py-2 text-sm text-cyan-100">
            {msg.text}
            {msg.detail && (
              <p className="mt-1 text-xs opacity-70">"{msg.detail}"</p>
            )}
          </div>
          <div className="mt-0.5 text-right text-[10px] text-slate-600">
            {fmtTime(msg.timestamp)}
          </div>
        </div>
      </div>
    )
  }

  // Other users' messages — left-aligned with sender name
  return (
    <div className="flex justify-start px-4 py-1.5">
      <div className="max-w-xs">
        {msg.senderName && (
          <div className="mb-0.5 text-[10px] font-medium text-slate-500">
            {msg.senderName}
          </div>
        )}
        <div className="rounded-2xl rounded-bl-sm bg-slate-800 px-3.5 py-2 text-sm text-slate-200">
          {msg.text}
          {msg.detail && (
            <p className="mt-1 text-xs opacity-70">"{msg.detail}"</p>
          )}
        </div>
        <div className="mt-0.5 text-[10px] text-slate-600">
          {fmtTime(msg.timestamp)}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Typing indicator
// ---------------------------------------------------------------------------

function TypingIndicator({ users }: { users: TypingState[] }) {
  if (users.length === 0) return null

  const names = users.map((u) => u.user_name).filter(Boolean)
  let text: string
  if (names.length === 1) {
    text = `${names[0]} is typing...`
  } else if (names.length === 2) {
    text = `${names[0]} and ${names[1]} are typing...`
  } else {
    text = `${names.length} people are typing...`
  }

  return (
    <div className="flex items-center gap-2 px-4 py-1 text-xs text-slate-500">
      <span className="flex gap-0.5">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500 [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500 [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500 [animation-delay:300ms]" />
      </span>
      <span>{text}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface ChatPanelProps {
  pipelineId: string
  state: PipelineState | null
  events: AgentEvent[]
  /** Chat messages received via WebSocket broadcast. */
  wsChatMessages?: WsChatMessage[]
  /** Typing states from other users. */
  typingUsers?: TypingState[]
  /** Send a WebSocket message (for typing indicators). */
  wsSend?: (msg: Record<string, unknown>) => void
  /** Current user ID for distinguishing own messages. */
  currentUserId?: string
  /** Current user name for approval attribution. */
  currentUserName?: string
  onViewArtifact?: (stage: string, data: Record<string, unknown>) => void
  className?: string
}

export default function ChatPanel({
  pipelineId,
  state,
  events,
  wsChatMessages = [],
  typingUsers = [],
  wsSend,
  currentUserId,
  currentUserName,
  onViewArtifact,
  className,
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([])
  const [persistedMessages, setPersistedMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load persisted messages on mount
  useEffect(() => {
    listPipelineMessages(pipelineId)
      .then((msgs) => {
        setPersistedMessages(
          msgs.map((m) => chatMsgToChatMessage(m, currentUserId)),
        )
      })
      .catch(() => {}) // silently fail on load
  }, [pipelineId, currentUserId])

  // Convert WebSocket chat messages to ChatMessage format
  const wsMessages = useMemo(
    () => wsChatMessages.map((m) => chatMsgToChatMessage(m, currentUserId)),
    [wsChatMessages, currentUserId],
  )

  // Merge event-derived messages with persisted, WS, and local messages
  const eventMessages = useMemo(() => eventsToChatMessages(events), [events])

  const allMessages = useMemo(() => {
    const seen = new Set<string>()
    const result: ChatMessage[] = []

    // Add persisted messages first
    for (const m of persistedMessages) {
      if (!seen.has(m.id)) {
        seen.add(m.id)
        result.push(m)
      }
    }

    // Add event-derived messages
    for (const m of eventMessages) {
      if (!seen.has(m.id)) {
        seen.add(m.id)
        result.push(m)
      }
    }

    // Add WebSocket chat messages (dedup by id)
    for (const m of wsMessages) {
      if (!seen.has(m.id)) {
        seen.add(m.id)
        result.push(m)
      }
    }

    // Add local (optimistic) messages not yet confirmed
    for (const m of localMessages) {
      if (!seen.has(m.id)) {
        seen.add(m.id)
        result.push(m)
      }
    }

    return result.sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
    )
  }, [persistedMessages, eventMessages, wsMessages, localMessages])

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (nearBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [allMessages.length])

  const addLocalMessage = useCallback((msg: ChatMessage) => {
    setLocalMessages((prev) => [...prev, msg])
  }, [])

  // Typing indicator: send typing state on input change
  function handleInputChange(value: string) {
    setInput(value)

    if (wsSend && value.trim()) {
      wsSend({ type: 'typing', is_typing: true })

      // Clear typing after 2s of no input
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current)
      typingTimerRef.current = setTimeout(() => {
        wsSend({ type: 'typing', is_typing: false })
      }, 2000)
    }
  }

  // Command handler
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setInput('')

    // Stop typing indicator
    if (wsSend) wsSend({ type: 'typing', is_typing: false })
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current)

    if (text.toLowerCase() === 'abort') {
      setSending(true)
      addLocalMessage({
        id: `local-${Date.now()}`,
        kind: 'human',
        text: 'abort',
        timestamp: new Date().toISOString(),
        variant: 'error',
        senderName: currentUserName,
        senderId: currentUserId,
      })
      try {
        await abortPipeline(pipelineId)
        addLocalMessage({
          id: `local-${Date.now()}-ack`,
          kind: 'system',
          text: 'Abort signal sent',
          timestamp: new Date().toISOString(),
          variant: 'error',
        })
      } catch (err) {
        addLocalMessage({
          id: `local-${Date.now()}-err`,
          kind: 'system',
          text: `Abort failed: ${err instanceof Error ? err.message : 'unknown'}`,
          timestamp: new Date().toISOString(),
          variant: 'error',
        })
      } finally {
        setSending(false)
      }
      return
    }

    if (text.toLowerCase() === 'status') {
      setSending(true)
      addLocalMessage({
        id: `local-${Date.now()}`,
        kind: 'human',
        text: 'status',
        timestamp: new Date().toISOString(),
        senderName: currentUserName,
        senderId: currentUserId,
      })
      try {
        const s = await getPipelineState(pipelineId)
        addLocalMessage({
          id: `local-${Date.now()}-status`,
          kind: 'status',
          text: `Stage: ${stageLabel(s.current_stage)} | Cost: $${s.total_cost_usd.toFixed(4)}/${s.max_cost_usd.toFixed(2)} | ${s.aborted ? 'ABORTED' : s.pending_approval ? `Awaiting: ${stageLabel(s.pending_approval)}` : 'Running'}`,
          timestamp: new Date().toISOString(),
          variant: 'info',
        })
      } catch (err) {
        addLocalMessage({
          id: `local-${Date.now()}-err`,
          kind: 'system',
          text: `Status query failed: ${err instanceof Error ? err.message : 'unknown'}`,
          timestamp: new Date().toISOString(),
          variant: 'error',
        })
      } finally {
        setSending(false)
      }
      return
    }

    // Free text → persist as chat message
    setSending(true)
    const optimisticId = `local-${Date.now()}`
    addLocalMessage({
      id: optimisticId,
      kind: 'chat',
      text,
      timestamp: new Date().toISOString(),
      senderName: currentUserName,
      senderId: currentUserId,
    })
    try {
      await createPipelineMessage(pipelineId, text)
    } catch {
      // Message was shown optimistically; if persist fails, it still shows locally
    } finally {
      setSending(false)
    }
  }

  // Terminal states
  const isComplete = state?.current_stage === 'complete'
  const isFailed = state?.aborted

  return (
    <div className={clsx('flex flex-col rounded-xl border border-slate-800 bg-slate-900/50', className)}>
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2.5">
        <MessageSquare className="h-4 w-4 text-slate-500" />
        <span className="text-sm font-medium text-slate-300">Chat</span>
        {state?.pending_approval && (
          <span className="ml-auto rounded-full bg-amber-900/60 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-300">
            Action needed
          </span>
        )}
      </div>

      {/* Message area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto py-3">
        {/* Approval card at top when pending */}
        {state?.pending_approval && (
          <div className="mb-3">
            <ApprovalCard
              state={state}
              pipelineId={pipelineId}
              userName={currentUserName}
              onAction={addLocalMessage}
              onViewArtifact={onViewArtifact}
            />
          </div>
        )}

        {/* Messages */}
        {allMessages.length === 0 && !state?.pending_approval ? (
          <EmptyState isComplete={isComplete} isFailed={isFailed} abortReason={state?.abort_reason} />
        ) : (
          allMessages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              isOwnMessage={msg.senderId === currentUserId || (msg.kind === 'human' && !msg.senderId)}
            />
          ))
        )}

        {/* Typing indicator */}
        <TypingIndicator users={typingUsers} />
      </div>

      {/* Input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 border-t border-slate-800 px-3 py-2.5"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => handleInputChange(e.target.value)}
          placeholder={isComplete || isFailed ? 'Pipeline finished' : 'Type a message or command...'}
          disabled={isComplete || isFailed}
          className="flex-1 rounded-lg border border-slate-700/50 bg-slate-800/60 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-700 focus:outline-none disabled:opacity-40"
        />
        <button
          type="submit"
          disabled={!input.trim() || sending || isComplete || isFailed}
          className="rounded-lg bg-cyan-600 p-2 text-white transition hover:bg-cyan-500 disabled:opacity-40"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty / terminal states
// ---------------------------------------------------------------------------

function EmptyState({
  isComplete,
  isFailed,
  abortReason,
}: {
  isComplete?: boolean
  isFailed?: boolean
  abortReason?: string
}) {
  if (isComplete) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <CheckCircle2 className="h-10 w-10 text-emerald-600" />
        <p className="mt-3 text-sm font-medium text-emerald-300">Pipeline Complete</p>
        <p className="mt-1 text-xs text-slate-500">All stages finished successfully.</p>
      </div>
    )
  }

  if (isFailed) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <XCircle className="h-10 w-10 text-red-600" />
        <p className="mt-3 text-sm font-medium text-red-300">Pipeline Failed</p>
        {abortReason && (
          <p className="mt-1 max-w-xs text-xs text-slate-500">{abortReason}</p>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <Terminal className="h-8 w-8 text-slate-700" />
      <p className="mt-3 text-sm text-slate-500">No activity yet</p>
      <p className="mt-1 text-xs text-slate-600">
        Stage transitions, approvals, and team messages will appear here.
      </p>
    </div>
  )
}
