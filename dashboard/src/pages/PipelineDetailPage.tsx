import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Clock,
  DollarSign,
  OctagonX,
  RefreshCw,
  TicketCheck,
  Timer,
  Trophy,
  Users,
  XCircle,
  Zap,
} from 'lucide-react'
import clsx from 'clsx'
import {
  abortPipeline,
  getConcurrencyMetrics,
  getPipeline,
  getPipelineState,
  getPipelineTickets,
  type ConcurrencyMetrics,
} from '../lib/api.ts'
import { useWebSocket } from '../hooks/useWebSocket.ts'
import { usePresence } from '../hooks/usePresence.ts'
import { useSession, useActiveOrganization } from '../lib/auth.ts'
import PipelineDAG from '../components/PipelineDAG.tsx'
import LogPanel from '../components/LogPanel.tsx'
import ChatPanel from '../components/ChatPanel.tsx'
import PresenceBar from '../components/PresenceBar.tsx'
import { type ArtifactKind } from '../components/ArtifactViewer.tsx'
import DetailPane, { type DetailSelection } from '../components/DetailPane.tsx'
import CostTracker from '../components/CostTracker.tsx'
import MemoryPanel from '../components/MemoryPanel.tsx'
import StageFeed from '../components/StageFeed.tsx'
import type {
  PipelineDetail,
  PipelineState,
  TicketExecution,
} from '../types/pipeline.ts'
import OrgSwitcher from '../components/OrgSwitcher.tsx'
import UserMenu from '../components/UserMenu.tsx'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATE_POLL_MS = 5_000
const TICKET_POLL_MS = 8_000

/** Maps pipeline stages to their artifact key on PipelineState. */
const STAGE_ARTIFACT: Record<string, { key: keyof PipelineState; kind: ArtifactKind }> = {
  business_analysis:  { key: 'product_spec',  kind: 'product_spec' },
  research:           { key: 'enriched_spec', kind: 'enriched_spec' },
  architecture:       { key: 'tech_spec',     kind: 'tech_spec' },
  task_decomposition: { key: 'prd_board',     kind: 'prd_board' },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stageLabel(stage: string): string {
  return stage.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatEta(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return s > 0 ? `${m}m${s}s` : `${m}m`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h}h${rm}m` : `${h}h`
}

const STATUS_BADGE: Record<string, string> = {
  complete:           'bg-emerald-900/60 text-emerald-300 ring-emerald-700/40',
  completed:          'bg-emerald-900/60 text-emerald-300 ring-emerald-700/40',
  running:            'bg-blue-900/60 text-blue-300 ring-blue-700/40',
  active:             'bg-blue-900/60 text-blue-300 ring-blue-700/40',
  awaiting_approval:  'bg-amber-900/60 text-amber-300 ring-amber-700/40',
  pending_approval:   'bg-amber-900/60 text-amber-300 ring-amber-700/40',
  failed:             'bg-red-900/60 text-red-300 ring-red-700/40',
  error:              'bg-red-900/60 text-red-300 ring-red-700/40',
  pending:            'bg-slate-700/60 text-slate-300 ring-slate-600/40',
}

// ---------------------------------------------------------------------------
// Elapsed time hook
// ---------------------------------------------------------------------------

function useElapsed(startIso: string | undefined): string {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!startIso) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [startIso])

  if (!startIso) return '--:--'

  const elapsed = Math.max(0, now - new Date(startIso).getTime())
  const totalSecs = Math.floor(elapsed / 1000)
  const h = Math.floor(totalSecs / 3600)
  const m = Math.floor((totalSecs % 3600) / 60)
  const s = totalSecs % 60

  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// Stats computation
// ---------------------------------------------------------------------------

interface PipelineStats {
  ticketsTotal: number
  ticketsCompleted: number
  qaPassRate: number | null
  revisionCount: number
  totalCost: number
}

function computeStats(
  state: PipelineState | null,
  tickets: TicketExecution[],
): PipelineStats {
  const ticketsTotal = tickets.length
  const ticketsCompleted = tickets.filter(
    (t) => t.status === 'completed' || t.status === 'complete',
  ).length

  const withVerdict = tickets.filter((t) => t.verdict)
  const passed = withVerdict.filter(
    (t) => t.verdict === 'pass' || t.verdict === 'passed' || t.verdict === 'approved',
  )
  const qaPassRate = withVerdict.length > 0
    ? Math.round((passed.length / withVerdict.length) * 100)
    : null

  const revisionCount = tickets.reduce(
    (sum, t) => sum + Math.max(0, t.attempts - 1),
    0,
  )

  return {
    ticketsTotal,
    ticketsCompleted,
    qaPassRate,
    revisionCount,
    totalCost: state?.total_cost_usd ?? 0,
  }
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PipelineDetailPage() {
  const { id } = useParams<{ id: string }>()

  // Data state
  const [detail, setDetail] = useState<PipelineDetail | null>(null)
  const [pipelineState, setPipelineState] = useState<PipelineState | null>(null)
  const [tickets, setTickets] = useState<TicketExecution[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Abort state
  const [aborting, setAborting] = useState(false)
  const [showAbortConfirm, setShowAbortConfirm] = useState(false)

  // Detail pane selection (artifact or ticket)
  const [selection, setSelection] = useState<DetailSelection | null>(null)

  // Ticket filter (from DAG click → LogPanel filter)
  const [selectedTicket, setSelectedTicket] = useState<string | null>(null)

  // Concurrency metrics
  const [concurrency, setConcurrency] = useState<ConcurrencyMetrics | null>(null)
  const concurrencyTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Auth session
  const { data: session } = useSession()
  const { data: activeOrg } = useActiveOrganization()
  const currentUserId = session?.user?.id
  const currentUserName = session?.user?.name ?? session?.user?.email
  const userRole =
    (activeOrg?.members as Record<string, unknown>[] | undefined)?.find(
      (m) => m.userId === currentUserId,
    )?.role as string ?? 'member'

  // WebSocket events (multiplayer)
  const { events, connected, online, chatMessages: wsChatMessages, typingUsers, send: wsSend } = useWebSocket(id)

  // Presence tracking
  const { users: presenceUsers } = usePresence(online, wsSend, currentUserId)

  // Cleared events (for LogPanel clear button)
  const [clearedAt, setClearedAt] = useState(0)
  const visibleEvents = useMemo(
    () => clearedAt > 0 ? events.filter((_, i) => i >= clearedAt) : events,
    [events, clearedAt],
  )

  // Elapsed time
  const elapsed = useElapsed(detail?.created_at)

  // Terminal state checks
  const isTerminal = pipelineState?.current_stage === 'complete' || pipelineState?.aborted

  // Stats
  const stats = useMemo(
    () => computeStats(pipelineState, tickets),
    [pipelineState, tickets],
  )

  // Polling ref to stop on unmount
  const stateTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const ticketTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ---- Initial fetch ----
  useEffect(() => {
    if (!id) return

    Promise.all([
      getPipeline(id),
      getPipelineState(id),
      getPipelineTickets(id),
    ])
      .then(([d, s, t]) => {
        setDetail(d)
        setPipelineState(s)
        setTickets(t)
      })
      .catch((err: Error) => {
        if (err.message.includes('404')) {
          setNotFound(true)
        } else {
          setError(err.message)
        }
      })
      .finally(() => setLoading(false))
  }, [id])

  // ---- State polling (every 5s) ----
  useEffect(() => {
    if (!id || notFound) return

    const poll = () => {
      getPipelineState(id)
        .then(setPipelineState)
        .catch(() => {}) // silently retry next tick
    }

    stateTimerRef.current = setInterval(poll, STATE_POLL_MS)
    return () => {
      if (stateTimerRef.current) clearInterval(stateTimerRef.current)
    }
  }, [id, notFound])

  // ---- Ticket polling (every 8s) ----
  useEffect(() => {
    if (!id || notFound) return

    const poll = () => {
      getPipelineTickets(id)
        .then(setTickets)
        .catch(() => {})
    }

    ticketTimerRef.current = setInterval(poll, TICKET_POLL_MS)
    return () => {
      if (ticketTimerRef.current) clearInterval(ticketTimerRef.current)
    }
  }, [id, notFound])

  // ---- Concurrency metrics polling (every 3s while running) ----
  useEffect(() => {
    if (!id || notFound || isTerminal) return

    const poll = () => {
      getConcurrencyMetrics(id)
        .then(setConcurrency)
        .catch(() => {})
    }
    poll() // immediate first fetch
    concurrencyTimerRef.current = setInterval(poll, 3_000)
    return () => {
      if (concurrencyTimerRef.current) clearInterval(concurrencyTimerRef.current)
    }
  }, [id, notFound, isTerminal])

  // Stop polling when terminal
  useEffect(() => {
    if (isTerminal) {
      if (stateTimerRef.current) clearInterval(stateTimerRef.current)
      if (ticketTimerRef.current) clearInterval(ticketTimerRef.current)
      if (concurrencyTimerRef.current) clearInterval(concurrencyTimerRef.current)
    }
  }, [isTerminal])

  // ---- Abort handler ----
  const handleAbort = useCallback(async () => {
    if (!id) return
    setAborting(true)
    try {
      await abortPipeline(id)
      setShowAbortConfirm(false)
      // State poll will pick up the change
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Abort failed')
    } finally {
      setAborting(false)
    }
  }, [id])

  // ---- Open artifact for a stage (from DAG click) ----
  const handleStageClick = useCallback(
    (stage: string) => {
      if (!pipelineState) return
      const mapping = STAGE_ARTIFACT[stage]
      if (!mapping) return
      const data = pipelineState[mapping.key]
      if (!data || typeof data !== 'object') return
      setSelection({
        type: 'artifact',
        kind: mapping.kind,
        data: data as Record<string, unknown>,
        title: `${stageLabel(stage)} — ${stageLabel(mapping.kind)}`,
      })
    },
    [pipelineState],
  )

  // ---- Open artifact from ChatPanel approval card ----
  const handleViewArtifact = useCallback(
    (stage: string, data: Record<string, unknown>) => {
      const mapping = STAGE_ARTIFACT[stage]
      setSelection({
        type: 'artifact',
        kind: mapping?.kind ?? 'product_spec',
        data,
        title: `${stageLabel(stage)} — Review`,
      })
    },
    [],
  )

  // ---- Open ticket detail (from DAG ticket node click) ----
  const handleTicketSelect = useCallback(
    (ticketKey: string, ticket?: TicketExecution, prdTicket?: Record<string, unknown>) => {
      setSelection({ type: 'ticket', ticketKey, ticket, prdTicket })
    },
    [],
  )

  // ---- Render: loading ----
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-500">
        <Activity className="mr-2 h-5 w-5 animate-spin" />
        Loading pipeline...
      </div>
    )
  }

  // ---- Render: 404 ----
  if (notFound) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-950">
        <div className="text-center">
          <div className="text-6xl font-bold text-slate-700">404</div>
          <p className="mt-2 text-slate-400">Pipeline not found</p>
          <p className="mt-1 font-mono text-sm text-slate-600">{id}</p>
          <Link
            to="/"
            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-300 transition hover:bg-slate-700"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to pipelines
          </Link>
        </div>
      </div>
    )
  }

  // ---- Render: error ----
  if (error && !detail) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950">
        <div className="rounded-lg border border-red-800 bg-red-950 px-6 py-4 text-red-300">
          {error}
        </div>
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to pipelines
        </Link>
      </div>
    )
  }

  const status = pipelineState?.aborted
    ? 'failed'
    : pipelineState?.pending_approval
      ? 'awaiting_approval'
      : pipelineState?.current_stage === 'complete'
        ? 'complete'
        : 'running'

  return (
    <div className="flex min-h-screen flex-col bg-slate-950">
      {/* ================================================================ */}
      {/* Top bar                                                          */}
      {/* ================================================================ */}
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-3">
          {/* Back + branding */}
          <Link to="/" className="text-slate-500 transition hover:text-slate-300">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-cyan-400" />
            <span className="text-sm font-bold text-slate-300">Forge</span>
          </div>

          {/* Pipeline ID */}
          <span className="font-mono text-sm text-slate-400">{id}</span>

          {/* Status badge */}
          <span
            className={clsx(
              'rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset',
              STATUS_BADGE[status] ?? STATUS_BADGE.pending,
            )}
          >
            {status === 'awaiting_approval' ? 'awaiting approval' : status}
          </span>

          {/* Current stage */}
          <span className="hidden text-xs text-slate-500 sm:inline">
            {pipelineState ? stageLabel(pipelineState.current_stage) : '...'}
          </span>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Cost tracker */}
          <CostTracker
            totalCost={pipelineState?.total_cost_usd ?? 0}
            maxCost={pipelineState?.max_cost_usd ?? 1}
            events={events}
          />

          {/* Concurrency metrics */}
          {concurrency && !isTerminal && (concurrency.active_engineers > 0 || concurrency.active_qa > 0) && (
            <div className="hidden items-center gap-3 sm:flex">
              <div
                className={clsx(
                  'flex items-center gap-1 text-xs',
                  concurrency.backpressure_active ? 'text-amber-400' : 'text-slate-400',
                )}
                title={`${concurrency.active_engineers}/${concurrency.max_concurrent_engineers} engineers, ${concurrency.active_qa}/${concurrency.max_concurrent_qa} QA`}
              >
                <Users className="h-3.5 w-3.5" />
                <span className="font-mono">
                  {concurrency.active_engineers + concurrency.active_qa}
                </span>
              </div>
              {concurrency.estimated_remaining_seconds != null && (
                <div
                  className="flex items-center gap-1 text-xs text-slate-500"
                  title="Estimated time remaining"
                >
                  <Clock className="h-3 w-3" />
                  <span className="font-mono">
                    ~{formatEta(concurrency.estimated_remaining_seconds)}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Elapsed */}
          <div className="flex items-center gap-1 text-sm text-slate-500">
            <Timer className="h-3.5 w-3.5" />
            <span className="font-mono">{elapsed}</span>
          </div>

          {/* Presence bar */}
          <PresenceBar
            users={presenceUsers}
            currentUserId={currentUserId}
          />

          {/* Connection indicator */}
          <div
            className={clsx(
              'h-2 w-2 rounded-full',
              connected ? 'bg-emerald-500' : 'bg-slate-600',
            )}
            title={connected ? 'WebSocket connected' : 'WebSocket disconnected'}
          />

          {/* Abort button */}
          {!isTerminal && (
            <div className="relative">
              <button
                onClick={() => setShowAbortConfirm((v) => !v)}
                className="rounded-lg border border-red-800/50 px-3 py-1.5 text-xs font-medium text-red-400 transition hover:bg-red-950/40"
              >
                <OctagonX className="inline h-3.5 w-3.5 mr-1" />
                Abort
              </button>
              {showAbortConfirm && (
                <div className="absolute right-0 top-full z-50 mt-2 rounded-lg border border-red-800 bg-slate-900 p-3 shadow-xl">
                  <p className="mb-2 text-xs text-slate-300">Abort this pipeline?</p>
                  <div className="flex gap-2">
                    <button
                      onClick={handleAbort}
                      disabled={aborting}
                      className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
                    >
                      {aborting ? 'Aborting...' : 'Confirm'}
                    </button>
                    <button
                      onClick={() => setShowAbortConfirm(false)}
                      className="rounded bg-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-600"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Org + User */}
          <OrgSwitcher />
          <UserMenu />
        </div>
      </header>

      {/* ================================================================ */}
      {/* Completion banner                                                */}
      {/* ================================================================ */}
      {pipelineState?.current_stage === 'complete' && (
        <div className="border-b border-emerald-800/40 bg-emerald-950/30 px-4 py-3">
          <div className="mx-auto flex max-w-[1600px] items-center gap-3">
            <Trophy className="h-5 w-5 text-emerald-400" />
            <span className="text-sm font-semibold text-emerald-300">Pipeline Completed</span>
            <span className="text-xs text-slate-400">
              {stats.ticketsCompleted}/{stats.ticketsTotal} tickets
              {stats.qaPassRate !== null && ` | ${stats.qaPassRate}% QA pass rate`}
              {` | $${stats.totalCost.toFixed(4)} cost`}
              {` | ${elapsed} elapsed`}
            </span>
          </div>
        </div>
      )}

      {pipelineState?.aborted && (
        <div className="border-b border-red-800/40 bg-red-950/30 px-4 py-3">
          <div className="mx-auto flex max-w-[1600px] items-center gap-3">
            <XCircle className="h-5 w-5 text-red-400" />
            <span className="text-sm font-semibold text-red-300">Pipeline Failed</span>
            <span className="text-xs text-slate-400">
              {pipelineState.abort_reason || 'Aborted'}
            </span>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Stats bar                                                        */}
      {/* ================================================================ */}
      {tickets.length > 0 && (
        <div className="border-b border-slate-800/60 bg-slate-900/30 px-4 py-2">
          <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-1">
            <StatChip
              icon={<TicketCheck className="h-3.5 w-3.5" />}
              label="Tickets"
              value={`${stats.ticketsCompleted}/${stats.ticketsTotal}`}
              color="text-cyan-400"
            />
            {stats.qaPassRate !== null && (
              <StatChip
                icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                label="QA Pass"
                value={`${stats.qaPassRate}%`}
                color={stats.qaPassRate >= 80 ? 'text-emerald-400' : stats.qaPassRate >= 50 ? 'text-amber-400' : 'text-red-400'}
              />
            )}
            <StatChip
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              label="Revisions"
              value={String(stats.revisionCount)}
              color="text-slate-400"
            />
            <StatChip
              icon={<DollarSign className="h-3.5 w-3.5" />}
              label="Cost"
              value={`$${stats.totalCost.toFixed(4)}`}
              color="text-slate-400"
              mono
            />
            <StatChip
              icon={<Clock className="h-3.5 w-3.5" />}
              label="Elapsed"
              value={elapsed}
              color="text-slate-500"
              mono
            />
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Main content — 3-panel layout                                    */}
      {/* ================================================================ */}
      <div className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 p-4 lg:flex-row">
        {/* Left panel: DAG + Log */}
        <div
          className={clsx(
            'flex min-h-0 flex-col gap-3 transition-all duration-200',
            selection ? 'lg:w-[35%]' : 'lg:w-[60%]',
            'lg:flex-initial',
          )}
        >
          {/* DAG */}
          {pipelineState && (
            <PipelineDAG
              state={pipelineState}
              tickets={tickets}
              onStageClick={handleStageClick}
              onTicketClick={setSelectedTicket}
              onTicketSelect={handleTicketSelect}
              className="h-[280px] shrink-0 lg:h-[340px]"
            />
          )}

          {/* Stage output feed — compact artifact summaries */}
          {pipelineState && (
            <StageFeed
              state={pipelineState}
              onViewArtifact={(kind, data, title) =>
                setSelection({ type: 'artifact', kind, data, title })
              }
            />
          )}

          {/* Log panel */}
          <LogPanel
            events={visibleEvents}
            onClear={() => setClearedAt(events.length)}
            ticketFilter={selectedTicket}
            onClearTicketFilter={() => setSelectedTicket(null)}
            className="min-h-[300px] flex-1"
          />

          {/* Memory panel */}
          <MemoryPanel
            pipelineId={id!}
            userRole={userRole}
            className="max-h-[400px]"
          />
        </div>

        {/* Center panel: Detail pane (conditional) */}
        {selection && (
          <DetailPane
            selection={selection}
            onClose={() => setSelection(null)}
            className="min-h-[400px] lg:w-[40%] lg:min-h-0"
          />
        )}

        {/* Right panel: Chat */}
        <ChatPanel
          pipelineId={id!}
          state={pipelineState}
          events={events}
          wsChatMessages={wsChatMessages}
          typingUsers={typingUsers}
          wsSend={wsSend}
          currentUserId={currentUserId}
          currentUserName={currentUserName}
          onViewArtifact={handleViewArtifact}
          className={clsx(
            'min-h-[400px] lg:min-h-0 transition-all duration-200',
            selection ? 'lg:w-[25%]' : 'lg:w-[40%]',
          )}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stat chip
// ---------------------------------------------------------------------------

function StatChip({
  icon,
  label,
  value,
  color,
  mono,
}: {
  icon: React.ReactNode
  label: string
  value: string
  color: string
  mono?: boolean
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className={color}>{icon}</span>
      <span className="text-slate-600">{label}</span>
      <span className={clsx(color, mono && 'font-mono')}>{value}</span>
    </div>
  )
}
