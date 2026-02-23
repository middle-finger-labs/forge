import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Brain,
  DollarSign,
  Lightbulb,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import {
  createMemoryLesson,
  deleteMemoryLesson,
  getCostSummary,
  getMemoryDecisions,
  getMemoryLessons,
  getMemoryStats,
} from '../lib/api.ts'
import type {
  CostSummary,
  MemoryDecision,
  MemoryLesson,
  MemoryStats,
} from '../types/pipeline.ts'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemoryPanelProps {
  pipelineId: string
  className?: string
  /** Current user role in the org — admin/owner can delete lessons */
  userRole?: string
}

type Tab = 'lessons' | 'decisions' | 'contributors' | 'costs'

// ---------------------------------------------------------------------------
// Tab button
// ---------------------------------------------------------------------------

function TabButton({
  active,
  icon,
  label,
  count,
  onClick,
}: {
  active: boolean
  icon: React.ReactNode
  label: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition',
        active
          ? 'bg-slate-700 text-slate-200'
          : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300',
      )}
    >
      {icon}
      {label}
      {count != null && count > 0 && (
        <span className="ml-1 rounded-full bg-slate-600 px-1.5 py-0.5 text-[10px] font-mono">
          {count}
        </span>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Cost bar chart
// ---------------------------------------------------------------------------

const TICKET_COLORS = [
  'bg-cyan-500',
  'bg-blue-500',
  'bg-purple-500',
  'bg-indigo-500',
  'bg-orange-500',
  'bg-yellow-500',
  'bg-emerald-500',
  'bg-pink-500',
]

function CostBreakdown({ data }: { data: CostSummary }) {
  const maxCost = useMemo(() => {
    const costs = data.tickets.map((t) => t.cost_usd)
    return Math.max(...costs, 0.001)
  }, [data.tickets])

  return (
    <div className="space-y-3">
      {/* Total */}
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">Total Cost</span>
        <span className="font-mono text-slate-200">
          ${data.total_cost_usd.toFixed(4)}
        </span>
      </div>

      {/* Ticket breakdown */}
      {data.tickets.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-slate-500">Per-Ticket Costs</div>
          {data.tickets.map((ticket, i) => {
            const pct = maxCost > 0 ? (ticket.cost_usd / maxCost) * 100 : 0
            const color = TICKET_COLORS[i % TICKET_COLORS.length]
            return (
              <div key={ticket.ticket_key} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">
                    {ticket.ticket_key}
                    {ticket.attempts > 1 && (
                      <span className="ml-1 text-amber-500">
                        ({ticket.attempts} attempts)
                      </span>
                    )}
                  </span>
                  <span className="font-mono text-slate-300">
                    ${ticket.cost_usd.toFixed(4)}
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={clsx(color, 'h-full rounded-full transition-all duration-500')}
                    style={{ width: `${Math.max(pct, 1)}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Stage events */}
      {data.stages.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-slate-500">Stage Activity</div>
          <div className="flex flex-wrap gap-2">
            {data.stages.map((s) => (
              <span
                key={s.stage}
                className="rounded-md bg-slate-800 px-2 py-1 text-[10px] text-slate-400"
              >
                {s.stage.replace(/_/g, ' ')}
                <span className="ml-1 font-mono text-slate-500">{s.event_count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Add Lesson Inline Form
// ---------------------------------------------------------------------------

function AddLessonForm({ onAdded }: { onAdded: () => void }) {
  const [content, setContent] = useState('')
  const [sending, setSending] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = content.trim()
    if (!trimmed) return
    setSending(true)
    try {
      await createMemoryLesson(trimmed)
      setContent('')
      onAdded()
      inputRef.current?.focus()
    } catch {
      // ignore
    } finally {
      setSending(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t border-slate-800/60 px-3 py-2">
      <input
        ref={inputRef}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Add a lesson manually..."
        className="min-w-0 flex-1 bg-transparent text-xs text-slate-300 placeholder-slate-600 outline-none"
      />
      <button
        type="submit"
        disabled={sending || !content.trim()}
        className="shrink-0 rounded p-1 text-slate-500 transition hover:bg-cyan-900/30 hover:text-cyan-400 disabled:opacity-30"
      >
        {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
      </button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Contributors tab
// ---------------------------------------------------------------------------

function ContributorsTab({ stats }: { stats: MemoryStats | null }) {
  const contributions = stats?.contributions_per_user ?? {}
  const entries = Object.entries(contributions).sort((a, b) => b[1] - a[1])

  if (entries.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-slate-600">
        No contributor data yet. Memories are automatically tagged as pipelines run.
      </p>
    )
  }

  const maxCount = entries[0]?.[1] ?? 1

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-slate-500">Memories contributed per user</div>
      {entries.map(([userId, count]) => {
        const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
        return (
          <div key={userId} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="truncate text-slate-400 font-mono">{userId.slice(0, 12)}...</span>
              <span className="font-mono text-slate-300">{count}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full rounded-full bg-purple-500 transition-all duration-500"
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
          </div>
        )
      })}

      {/* Per-role breakdown */}
      {stats && Object.keys(stats.lessons_per_role).length > 0 && (
        <>
          <div className="mt-3 text-xs font-medium text-slate-500">By agent role</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.lessons_per_role).map(([role, count]) => (
              <span
                key={role}
                className="rounded-md bg-slate-800 px-2 py-1 text-[10px] text-slate-400"
              >
                {role}
                <span className="ml-1 font-mono text-slate-500">{count}</span>
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MemoryPanel({ pipelineId, className, userRole }: MemoryPanelProps) {
  const [tab, setTab] = useState<Tab>('lessons')
  const [lessons, setLessons] = useState<MemoryLesson[]>([])
  const [decisions, setDecisions] = useState<MemoryDecision[]>([])
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canDelete = userRole === 'owner' || userRole === 'admin'

  // ---- Fetch data ----
  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [l, d, s] = await Promise.all([
        getMemoryLessons(),
        getMemoryDecisions(),
        getMemoryStats(),
      ])
      setLessons(l)
      setDecisions(d)
      setStats(s)

      // Cost summary is per-pipeline, may 404
      try {
        const cs = await getCostSummary(pipelineId)
        setCostSummary(cs)
      } catch {
        setCostSummary(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load memory data')
    } finally {
      setLoading(false)
    }
  }, [pipelineId])

  useEffect(() => {
    refresh()
  }, [refresh])

  // ---- Delete lesson ----
  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteMemoryLesson(id)
        setLessons((prev) => prev.filter((l) => l.id !== id))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Delete failed')
      }
    },
    [],
  )

  // ---- Format relative time ----
  const timeAgo = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60_000)
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  }

  return (
    <div
      className={clsx(
        'flex flex-col rounded-xl border border-slate-800 bg-slate-900/50',
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-800 px-4 py-3">
        <Brain className="h-4 w-4 text-purple-400" />
        <span className="text-sm font-semibold text-slate-200">Org Memory</span>

        {stats && (
          <span className="text-[10px] text-slate-500">
            {stats.total_lessons} lessons / {stats.total_decisions} decisions
          </span>
        )}

        <div className="flex-1" />

        <button
          onClick={refresh}
          disabled={loading}
          className="rounded-md p-1 text-slate-500 transition hover:bg-slate-800 hover:text-slate-300 disabled:opacity-50"
        >
          <RefreshCw className={clsx('h-3.5 w-3.5', loading && 'animate-spin')} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800/60 px-3 py-2">
        <TabButton
          active={tab === 'lessons'}
          icon={<Lightbulb className="h-3 w-3" />}
          label="Lessons"
          count={stats?.total_lessons}
          onClick={() => setTab('lessons')}
        />
        <TabButton
          active={tab === 'decisions'}
          icon={<BookOpen className="h-3 w-3" />}
          label="Decisions"
          count={stats?.total_decisions}
          onClick={() => setTab('decisions')}
        />
        <TabButton
          active={tab === 'contributors'}
          icon={<Users className="h-3 w-3" />}
          label="Team"
          onClick={() => setTab('contributors')}
        />
        <TabButton
          active={tab === 'costs'}
          icon={<DollarSign className="h-3 w-3" />}
          label="Costs"
          onClick={() => setTab('costs')}
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">
        {error && (
          <div className="mb-3 rounded-lg border border-red-800/50 bg-red-950/30 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        {loading && !stats && (
          <div className="flex items-center justify-center py-8 text-sm text-slate-500">
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            Loading...
          </div>
        )}

        {/* Lessons tab */}
        {tab === 'lessons' && (
          <div className="space-y-2">
            {lessons.length === 0 && !loading && (
              <p className="py-6 text-center text-xs text-slate-600">
                No lessons stored yet. Agents learn from completed pipelines.
              </p>
            )}
            {lessons.map((lesson) => (
              <div
                key={lesson.id}
                className="group flex items-start gap-2 rounded-lg border border-slate-800/50 bg-slate-800/30 px-3 py-2"
              >
                <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-slate-300">{lesson.content}</p>
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-600">
                    {lesson.agent_role && (
                      <span className="rounded bg-slate-700/50 px-1.5 py-0.5">
                        {lesson.agent_role}
                      </span>
                    )}
                    {lesson.user_id && (
                      <span className="font-mono">{lesson.user_id.slice(0, 8)}</span>
                    )}
                    <span>{timeAgo(lesson.created_at)}</span>
                  </div>
                </div>
                {canDelete && (
                  <button
                    onClick={() => handleDelete(lesson.id)}
                    className="shrink-0 rounded p-1 text-slate-700 opacity-0 transition hover:bg-red-950/40 hover:text-red-400 group-hover:opacity-100"
                    title="Delete lesson"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Decisions tab */}
        {tab === 'decisions' && (
          <div className="space-y-2">
            {decisions.length === 0 && !loading && (
              <p className="py-6 text-center text-xs text-slate-600">
                No decisions recorded yet.
              </p>
            )}
            {decisions.map((decision) => (
              <div
                key={decision.id}
                className="rounded-lg border border-slate-800/50 bg-slate-800/30 px-3 py-2"
              >
                <p className="text-xs text-slate-300">{decision.content}</p>
                <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-600">
                  {decision.metadata.decision_type != null && (
                    <span className="rounded bg-indigo-900/40 px-1.5 py-0.5 text-indigo-400">
                      {String(decision.metadata.decision_type)}
                    </span>
                  )}
                  {decision.pipeline_id && (
                    <span className="font-mono">{decision.pipeline_id}</span>
                  )}
                  <span>{timeAgo(decision.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Contributors tab */}
        {tab === 'contributors' && <ContributorsTab stats={stats} />}

        {/* Costs tab */}
        {tab === 'costs' && (
          <div>
            {costSummary ? (
              <CostBreakdown data={costSummary} />
            ) : (
              <p className="py-6 text-center text-xs text-slate-600">
                No cost data available for this pipeline.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Add lesson form (shown on lessons tab) */}
      {tab === 'lessons' && <AddLessonForm onAdded={refresh} />}
    </div>
  )
}
