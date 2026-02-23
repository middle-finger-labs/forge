import { useMemo } from 'react'
import {
  BookOpen,
  ChevronRight,
  LayoutList,
  Layers,
  Search,
  Server,
} from 'lucide-react'
import clsx from 'clsx'
import type { PipelineState } from '../types/pipeline.ts'
import type { ArtifactKind } from './ArtifactViewer.tsx'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StageFeedProps {
  state: PipelineState
  onViewArtifact: (kind: ArtifactKind, data: Record<string, unknown>, title: string) => void
  className?: string
}

interface StageSummary {
  key: string
  kind: ArtifactKind
  label: string
  icon: React.ReactNode
  color: string
  borderColor: string
  data: Record<string, unknown>
  bullets: string[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {}
}

function str(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

// ---------------------------------------------------------------------------
// Summarizers — extract 2-4 key bullets from each artifact
// ---------------------------------------------------------------------------

function summarizeProductSpec(data: Record<string, unknown>): string[] {
  const bullets: string[] = []
  const name = str(data.product_name ?? data.name)
  if (name) bullets.push(name)
  const stories = arr(data.user_stories)
  if (stories.length > 0) bullets.push(`${stories.length} user stories`)
  const metrics = arr(data.success_metrics)
  if (metrics.length > 0) bullets.push(`${metrics.length} success metrics`)
  const questions = arr(data.open_questions)
  if (questions.length > 0) bullets.push(`${questions.length} open questions`)
  return bullets
}

function summarizeEnrichedSpec(data: Record<string, unknown>): string[] {
  const bullets: string[] = []
  const original = obj(data.original_spec)
  const name = str(original.product_name ?? data.product_name ?? '')
  if (name) bullets.push(name)
  const findings = arr(data.research_findings)
  if (findings.length > 0) bullets.push(`${findings.length} research findings`)
  const competitors = arr(data.competitors)
  if (competitors.length > 0) bullets.push(`${competitors.length} competitors analyzed`)
  const changes = arr(data.recommended_changes)
  if (changes.length > 0) bullets.push(`${changes.length} recommended changes`)
  return bullets
}

function summarizeTechSpec(data: Record<string, unknown>): string[] {
  const bullets: string[] = []
  const stack = obj(data.tech_stack)
  const stackEntries = Object.entries(stack)
  if (stackEntries.length > 0) {
    // Show first 3 stack items as compact string
    const preview = stackEntries
      .slice(0, 3)
      .map(([k, v]) => `${k}: ${str(v)}`)
      .join(', ')
    bullets.push(preview)
  }
  const services = arr(data.services)
  if (services.length > 0) bullets.push(`${services.length} services`)
  const endpoints = arr(data.api_endpoints)
  if (endpoints.length > 0) bullets.push(`${endpoints.length} API endpoints`)
  const files = data.file_structure
  if (files && typeof files === 'object') {
    const count = Object.keys(files).length
    if (count > 0) bullets.push(`${count} files mapped`)
  }
  return bullets
}

function summarizePRDBoard(data: Record<string, unknown>): string[] {
  const bullets: string[] = []
  const tickets = arr(data.tickets)
  if (tickets.length > 0) bullets.push(`${tickets.length} tickets`)
  const groups = arr(data.execution_order)
  if (groups.length > 0) bullets.push(`${groups.length} parallel groups`)
  const critPath = arr(data.critical_path)
  if (critPath.length > 0) bullets.push(`Critical path: ${critPath.map(str).join(' → ')}`)
  // Count by priority
  const critical = tickets.filter((t) => obj(t).priority === 'critical').length
  const high = tickets.filter((t) => obj(t).priority === 'high').length
  if (critical > 0 || high > 0) {
    const parts: string[] = []
    if (critical > 0) parts.push(`${critical} critical`)
    if (high > 0) parts.push(`${high} high`)
    bullets.push(parts.join(', '))
  }
  return bullets
}

// ---------------------------------------------------------------------------
// Build summaries from pipeline state
// ---------------------------------------------------------------------------

function buildSummaries(state: PipelineState): StageSummary[] {
  const summaries: StageSummary[] = []

  if (state.product_spec && typeof state.product_spec === 'object') {
    const data = state.product_spec as Record<string, unknown>
    summaries.push({
      key: 'ba',
      kind: 'product_spec',
      label: 'Business Analysis',
      icon: <BookOpen className="h-3.5 w-3.5" />,
      color: 'text-blue-400',
      borderColor: 'border-l-blue-500',
      data,
      bullets: summarizeProductSpec(data),
    })
  }

  if (state.enriched_spec && typeof state.enriched_spec === 'object') {
    const data = state.enriched_spec as Record<string, unknown>
    summaries.push({
      key: 'research',
      kind: 'enriched_spec',
      label: 'Research',
      icon: <Search className="h-3.5 w-3.5" />,
      color: 'text-emerald-400',
      borderColor: 'border-l-emerald-500',
      data,
      bullets: summarizeEnrichedSpec(data),
    })
  }

  if (state.tech_spec && typeof state.tech_spec === 'object') {
    const data = state.tech_spec as Record<string, unknown>
    summaries.push({
      key: 'arch',
      kind: 'tech_spec',
      label: 'Architecture',
      icon: <Server className="h-3.5 w-3.5" />,
      color: 'text-purple-400',
      borderColor: 'border-l-purple-500',
      data,
      bullets: summarizeTechSpec(data),
    })
  }

  if (state.prd_board && typeof state.prd_board === 'object') {
    const data = state.prd_board as Record<string, unknown>
    summaries.push({
      key: 'pm',
      kind: 'prd_board',
      label: 'Task Decomposition',
      icon: <LayoutList className="h-3.5 w-3.5" />,
      color: 'text-orange-400',
      borderColor: 'border-l-orange-500',
      data,
      bullets: summarizePRDBoard(data),
    })
  }

  return summaries
}

// ---------------------------------------------------------------------------
// Single card
// ---------------------------------------------------------------------------

function StageCard({
  summary,
  onView,
}: {
  summary: StageSummary
  onView: () => void
}) {
  return (
    <button
      onClick={onView}
      className={clsx(
        'group flex w-full items-center gap-3 rounded-lg border border-slate-800/60 border-l-2 bg-slate-900/60 px-3 py-2 text-left transition hover:bg-slate-800/50',
        summary.borderColor,
      )}
    >
      <span className={clsx('shrink-0', summary.color)}>{summary.icon}</span>

      <div className="min-w-0 flex-1">
        <div className={clsx('text-[11px] font-semibold', summary.color)}>
          {summary.label}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
          {summary.bullets.map((b, i) => (
            <span key={i} className="text-[11px] text-slate-400">
              {i > 0 && <span className="mr-2 text-slate-700">·</span>}
              {b}
            </span>
          ))}
        </div>
      </div>

      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-700 transition group-hover:text-slate-400" />
    </button>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function StageFeed({ state, onViewArtifact, className }: StageFeedProps) {
  const summaries = useMemo(() => buildSummaries(state), [state])

  if (summaries.length === 0) return null

  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      <div className="flex items-center gap-2 px-1">
        <Layers className="h-3 w-3 text-slate-600" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
          Stage Outputs
        </span>
      </div>
      {summaries.map((s) => (
        <StageCard
          key={s.key}
          summary={s}
          onView={() => onViewArtifact(s.kind, s.data, `${s.label} — ${s.kind.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}`)}
        />
      ))}
    </div>
  )
}
