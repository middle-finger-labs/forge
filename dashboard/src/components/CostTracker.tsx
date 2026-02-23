import { useMemo } from 'react'
import { AlertTriangle, DollarSign, TrendingDown } from 'lucide-react'
import clsx from 'clsx'
import type { AgentEvent } from '../types/pipeline.ts'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CostTrackerProps {
  totalCost: number
  maxCost: number
  events: AgentEvent[]
  className?: string
}

// ---------------------------------------------------------------------------
// Stage cost breakdown
// ---------------------------------------------------------------------------

const COST_STAGES = [
  { key: 'business_analysis', label: 'BA',   color: 'bg-blue-500' },
  { key: 'research',          label: 'Res',  color: 'bg-purple-500' },
  { key: 'architecture',      label: 'Arch', color: 'bg-indigo-500' },
  { key: 'task_decomposition', label: 'PM',  color: 'bg-orange-500' },
  { key: 'coding',            label: 'Code', color: 'bg-cyan-500' },
  { key: 'qa_review',         label: 'QA',   color: 'bg-yellow-500' },
] as const

/**
 * Estimate per-stage cost breakdown from events.
 * Looks for cost.update / stage.completed events that carry cost deltas,
 * otherwise distributes evenly across completed stages.
 */
function computeStageCosts(
  events: AgentEvent[],
  totalCost: number,
): Map<string, number> {
  const costs = new Map<string, number>()

  // Try extracting explicit cost data from events
  for (const evt of events) {
    if (evt.event_type === 'stage.completed' && evt.stage) {
      const cost = evt.payload.cost_usd ?? evt.payload.stage_cost ?? evt.payload.cost
      if (cost != null) {
        costs.set(evt.stage, (costs.get(evt.stage) ?? 0) + Number(cost))
      }
    }
    if (evt.event_type === 'cost.update' || evt.event_type === 'cost.alert') {
      const stage = evt.stage ?? String(evt.payload.stage ?? '')
      const cost = evt.payload.delta ?? evt.payload.cost_usd ?? evt.payload.cost
      if (stage && cost != null) {
        costs.set(stage, (costs.get(stage) ?? 0) + Number(cost))
      }
    }
  }

  // If we got explicit costs, return them
  if (costs.size > 0) return costs

  // Fallback: distribute total evenly across completed stages
  const completed = new Set<string>()
  for (const evt of events) {
    if (evt.event_type === 'stage.completed' && evt.stage) {
      completed.add(evt.stage)
    }
  }
  if (completed.size > 0) {
    const per = totalCost / completed.size
    for (const s of completed) costs.set(s, per)
  }

  return costs
}

/**
 * Extract the latest budget status from cost.alert / cost.warning /
 * cost.kill_switch events emitted by the BudgetManager.
 */
function extractBudgetStatus(events: AgentEvent[]): {
  remaining: number | null
  utilisation: number | null
  modelDowngraded: boolean
  message: string
} {
  let remaining: number | null = null
  let utilisation: number | null = null
  let modelDowngraded = false
  let message = ''

  for (const evt of events) {
    if (
      evt.event_type === 'cost.alert' ||
      evt.event_type === 'cost.warning' ||
      evt.event_type === 'cost.kill_switch'
    ) {
      if (evt.payload.remaining != null) remaining = Number(evt.payload.remaining)
      if (evt.payload.utilisation_pct != null) utilisation = Number(evt.payload.utilisation_pct)
      if (evt.payload.message) message = String(evt.payload.message)
      if (evt.payload.action === 'model_downgrade') modelDowngraded = true
    }
  }

  return { remaining, utilisation, modelDowngraded, message }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CostTracker({
  totalCost,
  maxCost,
  events,
  className,
}: CostTrackerProps) {
  const ratio = maxCost > 0 ? totalCost / maxCost : 0
  const pct = Math.min(ratio * 100, 100)

  const stageCosts = useMemo(
    () => computeStageCosts(events, totalCost),
    [events, totalCost],
  )

  // Total from stage breakdown (may differ from totalCost if we only have estimates)
  const stageCostTotal = useMemo(() => {
    let sum = 0
    for (const v of stageCosts.values()) sum += v
    return sum || 1 // avoid /0
  }, [stageCosts])

  const budgetInfo = useMemo(() => extractBudgetStatus(events), [events])
  const remaining = budgetInfo.remaining ?? Math.max(maxCost - totalCost, 0)

  const overHalf = ratio >= 0.5
  const overEighty = ratio >= 0.8
  const overFull = ratio >= 1.0

  return (
    <div className={clsx('flex items-center gap-2', className)}>
      {/* Dollar amount */}
      <div className={clsx(
        'flex items-center gap-1 font-mono text-sm transition-colors',
        overFull
          ? 'text-red-500 animate-pulse'
          : overEighty
            ? 'text-red-400'
            : overHalf
              ? 'text-amber-400'
              : 'text-slate-400',
      )}>
        <DollarSign className="h-3.5 w-3.5" />
        <span>{totalCost.toFixed(4)}</span>
      </div>

      {/* Budget bar */}
      <div
        className={clsx(
          'hidden h-4 w-32 overflow-hidden rounded-full border sm:flex',
          overFull
            ? 'border-red-600/80'
            : overEighty
              ? 'border-red-800/60'
              : overHalf
                ? 'border-amber-800/60'
                : 'border-slate-700/60',
        )}
        title={`$${totalCost.toFixed(4)} / $${maxCost.toFixed(2)} (${pct.toFixed(0)}%) — $${remaining.toFixed(2)} remaining`}
      >
        {/* Background */}
        <div className="relative flex h-full w-full bg-slate-800/60">
          {/* Stage segments */}
          {COST_STAGES.map(({ key, color, label }) => {
            const cost = stageCosts.get(key)
            if (!cost) return null
            const w = (cost / stageCostTotal) * pct
            return (
              <div
                key={key}
                className={clsx(color, 'h-full transition-all duration-500')}
                style={{ width: `${w}%` }}
                title={`${label}: $${cost.toFixed(4)}`}
              />
            )
          })}

          {/* Budget threshold markers */}
          <div
            className="absolute top-0 h-full w-px bg-amber-500/50"
            style={{ left: '50%' }}
            title="50% — Warning"
          />
          <div
            className="absolute top-0 h-full w-px bg-red-500/50"
            style={{ left: '80%' }}
            title="80% — Alert (model downgrade)"
          />
          <div
            className="absolute top-0 h-full w-0.5 bg-red-600/80"
            style={{ left: '100%' }}
            title="100% — Hard stop"
          />
        </div>
      </div>

      {/* Remaining cost + percentage */}
      <div className="hidden items-center gap-1.5 sm:flex">
        {maxCost > 0 && (
          <span className={clsx(
            'text-[10px] font-mono',
            overFull ? 'text-red-500' : overEighty ? 'text-red-500' : overHalf ? 'text-amber-500' : 'text-slate-600',
          )}>
            {pct.toFixed(0)}%
          </span>
        )}

        {/* Estimated remaining */}
        {remaining > 0 && !overFull && (
          <span className="text-[10px] font-mono text-slate-500" title="Estimated remaining budget">
            (${remaining.toFixed(2)} left)
          </span>
        )}
      </div>

      {/* Status indicators */}
      {overEighty && !overFull && (
        <AlertTriangle
          className="h-3.5 w-3.5 text-red-400"
          aria-label={budgetInfo.message || 'Cost alert: 80% budget used'}
        />
      )}
      {budgetInfo.modelDowngraded && (
        <TrendingDown
          className="h-3.5 w-3.5 text-amber-400"
          aria-label="Models downgraded to reduce costs"
        />
      )}
      {overFull && (
        <span className="text-[10px] font-bold text-red-500 animate-pulse">
          OVER BUDGET
        </span>
      )}
    </div>
  )
}
