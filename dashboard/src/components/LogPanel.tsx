import { memo, useCallback, useMemo, useRef, useState } from 'react'
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso'
import {
  ArrowDown,
  Filter,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import type { AgentEvent } from '../types/pipeline.ts'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENT_ROLES = [
  'ba',
  'researcher',
  'architect',
  'pm',
  'engineer',
  'qa',
  'cto',
] as const

type AgentRole = (typeof AGENT_ROLES)[number]

const ROLE_STYLE: Record<AgentRole, { bg: string; text: string; label: string }> = {
  ba:         { bg: 'bg-blue-900/60',   text: 'text-blue-300',    label: 'BA' },
  researcher: { bg: 'bg-emerald-900/60', text: 'text-emerald-300', label: 'RES' },
  architect:  { bg: 'bg-purple-900/60',  text: 'text-purple-300',  label: 'ARCH' },
  pm:         { bg: 'bg-orange-900/60',  text: 'text-orange-300',  label: 'PM' },
  engineer:   { bg: 'bg-cyan-900/60',    text: 'text-cyan-300',    label: 'ENG' },
  qa:         { bg: 'bg-red-900/60',     text: 'text-red-300',     label: 'QA' },
  cto:        { bg: 'bg-yellow-900/60',  text: 'text-yellow-300',  label: 'CTO' },
}

/** Event types that get special visual treatment.
 *  The workflow emits dot-notation names (e.g. "pipeline.completed").
 */
const HIGHLIGHT_EVENTS: Record<string, string> = {
  'human.approval_required': 'border-l-amber-500 bg-amber-950/20',
  'cto.intervention':        'border-l-yellow-500 bg-yellow-950/20',
  'cost.alert':              'border-l-red-500 bg-red-950/20',
  'cost.warning':            'border-l-red-500/60 bg-red-950/10',
  'cost.kill_switch':        'border-l-red-600 bg-red-950/40',
  'pipeline.completed':      'border-l-emerald-500 bg-emerald-950/20',
  'pipeline.failed':         'border-l-red-500 bg-red-950/30',
  'stage.error':             'border-l-orange-500 bg-orange-950/20',
  'group.failed':            'border-l-orange-500 bg-orange-950/20',
}

const PROMINENT_EVENTS = new Set(['pipeline.completed', 'pipeline.failed'])

// ---------------------------------------------------------------------------
// Timestamp formatting
// ---------------------------------------------------------------------------

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  const s = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${h}:${m}:${s}.${ms}`
}

// ---------------------------------------------------------------------------
// Payload summary extraction
// ---------------------------------------------------------------------------

function summarizeEvent(evt: AgentEvent): string {
  const p = evt.payload
  switch (evt.event_type) {
    case 'stage.started':
      return `Stage ${evt.stage ?? p.stage ?? '?'} started`
    case 'stage.completed': {
      const dur = p.duration_seconds != null
        ? ` (${Number(p.duration_seconds).toFixed(1)}s)`
        : p.duration_s != null ? ` (${Number(p.duration_s).toFixed(1)}s)` : ''
      const cost = p.cost_usd != null ? ` $${Number(p.cost_usd).toFixed(4)}` : ''
      return `Stage ${evt.stage ?? p.stage ?? '?'} completed${dur}${cost}`
    }
    case 'stage.error':
      return `${p.error_type ?? 'Error'} in ${evt.stage ?? '?'} (attempt ${p.attempt}/${p.max_retries})${p.is_retryable ? ' — retrying' : ''}`
    case 'pipeline.started':
      return 'Pipeline started'
    case 'pipeline.completed':
      return 'Pipeline completed successfully'
    case 'pipeline.failed':
      return `Pipeline failed: ${p.reason ?? p.error ?? '?'}`
    case 'qa.verdict': {
      const verdict = String(p.verdict ?? '?')
      const score = p.score != null ? ` (${p.score})` : ''
      return `${p.ticket_key ?? p.ticket_id ?? '?'} ${verdict}${score}`
    }
    case 'qa.auto_approved':
      return `${p.ticket_key ?? '?'} auto-approved`
    case 'human.approval_required':
      return `Approval needed for ${evt.stage ?? p.stage ?? '?'}`
    case 'human.approval_received':
      return `Approval received for ${evt.stage ?? p.stage ?? '?'}`
    case 'cto.intervention':
      return `CTO triggered: ${p.trigger_type ?? p.trigger ?? p.reason ?? '?'}`
    case 'cost.alert':
      return `Cost alert: $${Number(p.current_cost ?? p.cost ?? 0).toFixed(4)} / $${Number(p.max_cost ?? p.budget ?? 0).toFixed(2)}`
    case 'cost.warning':
      return `Cost warning: ${Number(p.utilisation_pct ?? 0).toFixed(0)}% of budget`
    case 'cost.kill_switch':
      return `Budget exceeded — pipeline stopped`
    case 'error.model_downgrade':
      return `Model downgraded to reduce costs`
    case 'group.started':
      return `Coding group ${p.group_index ?? '?'} started (${p.ticket_count ?? '?'} tickets)`
    case 'group.completed':
      return `Coding group ${p.group_index ?? '?'} completed`
    case 'group.failed':
      return `Coding group failed: ${p.error_type ?? p.message ?? '?'}`
    case 'scaffold.completed':
      return `Project scaffolded at ${p.repo_path ?? '?'}`
    case 'validation.started':
      return 'Validating execution order'
    case 'validation.passed':
      return 'Execution order validated'
    case 'validation.failed':
      return `Validation failed: ${Array.isArray(p.errors) ? (p.errors as string[]).length : 0} errors`
    case 'integration_check.started':
      return 'Running integration tests'
    case 'integration_check.passed':
      return 'Integration tests passed'
    case 'integration_check.failed':
      return `Integration tests failed`

    // LLM-level streaming events
    case 'llm.request_started':
      return `LLM call → ${p.model ?? '?'} (${p.message_count ?? '?'} msgs)`
    case 'llm.request_completed': {
      const lat = p.latency_ms != null ? ` ${Number(p.latency_ms).toFixed(0)}ms` : ''
      const tok = p.output_tokens != null ? ` ${p.output_tokens}tok` : ''
      const llmCost = p.cost_usd != null ? ` $${Number(p.cost_usd).toFixed(4)}` : ''
      return `LLM ✓ ${p.model ?? '?'}${lat}${tok}${llmCost}`
    }
    case 'llm.request_failed':
      return `LLM ✗ ${p.model ?? '?'} — ${p.error_category ?? p.error ?? '?'}`
    case 'llm.model_selected':
      return `Model selected: ${p.model ?? '?'}${p.is_fallback ? ' (fallback)' : ''}`

    // PM elastic decomposition events
    case 'pm.sketch_started':
      return 'PM sketch phase started'
    case 'pm.sketch_completed': {
      const tc = p.ticket_count != null ? ` (${p.ticket_count} tickets)` : ''
      return `PM sketch completed${tc}`
    }
    case 'pm.detail_started':
      return `Detailing ticket ${p.ticket_key ?? '?'}`
    case 'pm.detail_completed':
      return `Detailed ${p.ticket_key ?? '?'} (${p.story_points ?? '?'}sp)`
    case 'pm.decomposition_complete': {
      const tickets = p.ticket_count != null ? `${p.ticket_count} tickets` : '?'
      const groups = p.group_count != null ? `, ${p.group_count} groups` : ''
      return `Decomposition complete: ${tickets}${groups}`
    }

    default: {
      // Generic: take first few scalar payload values
      const parts = Object.entries(p)
        .filter(([, v]) => typeof v !== 'object')
        .slice(0, 3)
        .map(([k, v]) => `${k}=${v}`)
      return parts.length > 0 ? parts.join(' ') : ''
    }
  }
}

// ---------------------------------------------------------------------------
// Verdict coloring
// ---------------------------------------------------------------------------

function verdictColor(verdict: string): string {
  const v = verdict.toLowerCase()
  if (v === 'pass' || v === 'passed' || v === 'approved') return 'text-emerald-400'
  if (v === 'fail' || v === 'failed' || v === 'rejected') return 'text-red-400'
  if (v === 'revise' || v === 'needs_revision') return 'text-amber-400'
  return 'text-slate-400'
}

// ---------------------------------------------------------------------------
// Event type color
// ---------------------------------------------------------------------------

function eventTypeColor(type: string): string {
  if (type.startsWith('stage.'))              return 'text-indigo-400'
  if (type.startsWith('qa.'))                 return 'text-yellow-400'
  if (type.startsWith('pipeline.'))           return 'text-slate-300'
  if (type.startsWith('cost.'))               return 'text-red-400'
  if (type.startsWith('cto.'))                return 'text-yellow-400'
  if (type.startsWith('human.'))              return 'text-amber-400'
  if (type.startsWith('error.'))              return 'text-orange-400'
  if (type.startsWith('group.'))              return 'text-cyan-400'
  if (type.startsWith('validation.'))         return 'text-indigo-400'
  if (type.startsWith('integration_check.'))  return 'text-teal-400'
  if (type.startsWith('scaffold.'))           return 'text-emerald-400'
  if (type.startsWith('tickets.'))            return 'text-teal-400'
  if (type.startsWith('llm.'))               return 'text-sky-400'
  if (type.startsWith('pm.'))                return 'text-orange-400'
  return 'text-slate-500'
}

// ---------------------------------------------------------------------------
// Role badge component
// ---------------------------------------------------------------------------

function RoleBadge({ role }: { role: string }) {
  const normalized = role.toLowerCase().replace(/[-_ ]/g, '') as string
  // Map common role variants to our canonical names
  const key: AgentRole | undefined =
    normalized.includes('business') || normalized === 'ba' ? 'ba'
    : normalized.includes('research') ? 'researcher'
    : normalized.includes('arch') ? 'architect'
    : normalized === 'pm' || normalized.includes('product') ? 'pm'
    : normalized.includes('eng') || normalized.includes('cod') || normalized.includes('dev') ? 'engineer'
    : normalized === 'qa' || normalized.includes('quality') || normalized.includes('review') ? 'qa'
    : normalized === 'cto' || normalized.includes('chief') ? 'cto'
    : undefined

  const style = key ? ROLE_STYLE[key] : { bg: 'bg-slate-700/60', text: 'text-slate-400', label: role.slice(0, 4).toUpperCase() }

  return (
    <span className={clsx('inline-block w-10 rounded px-1 py-px text-center text-[10px] font-bold uppercase leading-tight', style.bg, style.text)}>
      {style.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Single log row
// ---------------------------------------------------------------------------

const LogRow = memo(function LogRow({
  event,
  isOdd,
}: {
  event: AgentEvent
  isOdd: boolean
}) {
  const highlight = HIGHLIGHT_EVENTS[event.event_type]
  const isProminent = PROMINENT_EVENTS.has(event.event_type)
  const ts = event.timestamp ?? event.created_at
  const summary = summarizeEvent(event)

  return (
    <div
      className={clsx(
        'flex items-baseline gap-2 border-l-2 px-3 font-mono text-xs leading-6',
        highlight ?? (isOdd ? 'border-l-transparent bg-slate-900/40' : 'border-l-transparent'),
        isProminent && 'py-1 text-sm font-semibold',
      )}
    >
      {/* Timestamp */}
      <span className="shrink-0 text-slate-600 select-none">
        {fmtTime(ts)}
      </span>

      {/* Agent role badge */}
      {event.agent_role ? (
        <RoleBadge role={event.agent_role} />
      ) : (
        <span className="inline-block w-10" />
      )}

      {/* Event type */}
      <span className={clsx('shrink-0 font-semibold', eventTypeColor(event.event_type))}>
        {event.event_type}
      </span>

      {/* Summary */}
      {event.event_type === 'qa.verdict' && event.payload.verdict ? (
        <span className="min-w-0 truncate text-slate-400">
          {String(event.payload.ticket_id ?? event.payload.ticket_key ?? '?')}{' '}
          <span className={verdictColor(String(event.payload.verdict))}>
            {String(event.payload.verdict)}
          </span>
          {event.payload.score != null && (
            <span className="text-slate-500"> ({String(event.payload.score)})</span>
          )}
        </span>
      ) : (
        <span className={clsx(
          'min-w-0 truncate',
          isProminent ? 'text-slate-200' : 'text-slate-400',
        )}>
          {summary}
        </span>
      )}
    </div>
  )
})

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface LogPanelProps {
  events: AgentEvent[]
  className?: string
  onClear?: () => void
  ticketFilter?: string | null
  onClearTicketFilter?: () => void
}

export default function LogPanel({ events, className, onClear, ticketFilter, onClearTicketFilter }: LogPanelProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [searchText, setSearchText] = useState('')
  const [activeRoles, setActiveRoles] = useState<Set<AgentRole>>(new Set())
  const [eventTypeFilter, setEventTypeFilter] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  // Derive the set of event types present in the stream for the dropdown
  const eventTypes = useMemo(() => {
    const types = new Set<string>()
    for (const e of events) types.add(e.event_type)
    return Array.from(types).sort()
  }, [events])

  // Filtered events
  const filtered = useMemo(() => {
    let list = events

    // Ticket filter (from DAG click)
    if (ticketFilter) {
      const tk = ticketFilter.toLowerCase()
      list = list.filter((e) => {
        const p = e.payload
        const ticketId = (p.ticket_id ?? p.ticket_key ?? '') as string
        return ticketId.toLowerCase() === tk
      })
    }

    if (activeRoles.size > 0) {
      list = list.filter((e) => {
        if (!e.agent_role) return false
        const normalized = e.agent_role.toLowerCase().replace(/[-_ ]/g, '')
        return AGENT_ROLES.some((r) => {
          if (!activeRoles.has(r)) return false
          const style = ROLE_STYLE[r]
          // Use same matching logic as RoleBadge
          if (r === 'ba') return normalized.includes('business') || normalized === 'ba'
          if (r === 'researcher') return normalized.includes('research')
          if (r === 'architect') return normalized.includes('arch')
          if (r === 'pm') return normalized === 'pm' || normalized.includes('product')
          if (r === 'engineer') return normalized.includes('eng') || normalized.includes('cod') || normalized.includes('dev')
          if (r === 'qa') return normalized === 'qa' || normalized.includes('quality') || normalized.includes('review')
          if (r === 'cto') return normalized === 'cto' || normalized.includes('chief')
          return style.label.toLowerCase() === normalized
        })
      })
    }

    if (eventTypeFilter) {
      list = list.filter((e) => e.event_type === eventTypeFilter)
    }

    if (searchText) {
      const q = searchText.toLowerCase()
      list = list.filter(
        (e) =>
          e.event_type.toLowerCase().includes(q) ||
          (e.agent_role?.toLowerCase().includes(q) ?? false) ||
          (e.stage?.toLowerCase().includes(q) ?? false) ||
          JSON.stringify(e.payload).toLowerCase().includes(q),
      )
    }

    return list
  }, [events, activeRoles, eventTypeFilter, searchText])

  const toggleRole = useCallback((role: AgentRole) => {
    setActiveRoles((prev) => {
      const next = new Set(prev)
      if (next.has(role)) next.delete(role)
      else next.add(role)
      return next
    })
  }, [])

  const scrollToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({
      index: filtered.length - 1,
      behavior: 'smooth',
    })
  }, [filtered.length])

  const handleFollowOutput = useCallback(
    (isAtBottom: boolean) => (isAtBottom ? 'smooth' as const : false as const),
    [],
  )

  const itemContent = useCallback(
    (index: number) => (
      <LogRow event={filtered[index]} isOdd={index % 2 === 1} />
    ),
    [filtered],
  )

  const hasFilters = activeRoles.size > 0 || !!eventTypeFilter || !!searchText || !!ticketFilter

  return (
    <div className={clsx('flex flex-col rounded-xl border border-slate-800 bg-[#0c0e14]', className)}>
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-2">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-600" />
          <input
            type="text"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search events..."
            className="w-full rounded-md border border-slate-700/50 bg-slate-900/60 py-1 pl-7 pr-7 font-mono text-xs text-slate-300 placeholder:text-slate-600 focus:border-cyan-700 focus:outline-none"
          />
          {searchText && (
            <button
              onClick={() => setSearchText('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Filter toggle */}
        <button
          onClick={() => setShowFilters((v) => !v)}
          className={clsx(
            'rounded-md border p-1.5 transition',
            showFilters || hasFilters
              ? 'border-cyan-700 bg-cyan-950/40 text-cyan-400'
              : 'border-slate-700/50 text-slate-500 hover:text-slate-300',
          )}
          title="Toggle filters"
        >
          <Filter className="h-3.5 w-3.5" />
        </button>

        {/* Ticket filter badge */}
        {ticketFilter && (
          <button
            onClick={onClearTicketFilter}
            className="flex items-center gap-1 rounded-md border border-cyan-700/60 bg-cyan-950/40 px-2 py-0.5 text-[11px] font-mono text-cyan-400 transition hover:bg-cyan-900/40"
            title="Clear ticket filter"
          >
            {ticketFilter}
            <X className="h-3 w-3" />
          </button>
        )}

        {/* Event count */}
        <span className="font-mono text-[11px] text-slate-600 select-none">
          {filtered.length === events.length
            ? `${events.length}`
            : `${filtered.length}/${events.length}`}
        </span>

        {/* Clear */}
        {onClear && (
          <button
            onClick={onClear}
            className="rounded-md border border-slate-700/50 p-1.5 text-slate-500 transition hover:border-red-800 hover:text-red-400"
            title="Clear events"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Filter bar */}
      {showFilters && (
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-800/60 px-3 py-2">
          {/* Role toggles */}
          {AGENT_ROLES.map((role) => {
            const s = ROLE_STYLE[role]
            const active = activeRoles.has(role)
            return (
              <button
                key={role}
                onClick={() => toggleRole(role)}
                className={clsx(
                  'rounded px-2 py-0.5 text-[10px] font-bold uppercase transition',
                  active
                    ? clsx(s.bg, s.text, 'ring-1 ring-inset ring-current')
                    : 'bg-slate-800/40 text-slate-600 hover:text-slate-400',
                )}
              >
                {s.label}
              </button>
            )
          })}

          {/* Divider */}
          <div className="h-4 w-px bg-slate-700/50" />

          {/* Event type dropdown */}
          <select
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            className="rounded-md border border-slate-700/50 bg-slate-900/60 px-2 py-0.5 font-mono text-[11px] text-slate-400 focus:border-cyan-700 focus:outline-none"
          >
            <option value="">All events</option>
            {eventTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          {/* Clear filters */}
          {hasFilters && (
            <button
              onClick={() => {
                setActiveRoles(new Set())
                setEventTypeFilter('')
                setSearchText('')
              }}
              className="ml-auto text-[11px] text-slate-500 hover:text-slate-300"
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {/* Virtualized log */}
      <div className="relative flex-1">
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center py-12 font-mono text-xs text-slate-600">
            {events.length === 0 ? 'Waiting for events...' : 'No events match filters'}
          </div>
        ) : (
          <Virtuoso
            ref={virtuosoRef}
            totalCount={filtered.length}
            itemContent={itemContent}
            followOutput={handleFollowOutput}
            atBottomStateChange={setAtBottom}
            atBottomThreshold={40}
            overscan={200}
            style={{ height: '100%' }}
          />
        )}

        {/* Scroll-to-bottom FAB */}
        {!atBottom && filtered.length > 0 && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-3 right-3 rounded-full border border-slate-700 bg-slate-800 p-2 text-slate-400 shadow-lg transition hover:bg-slate-700 hover:text-slate-200"
            title="Scroll to bottom"
          >
            <ArrowDown className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}
