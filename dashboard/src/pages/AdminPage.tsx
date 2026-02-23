import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle,
  Cpu,
  DollarSign,
  RefreshCw,
  Save,
  Server,
  XCircle,
  Zap,
} from 'lucide-react'
import clsx from 'clsx'
import {
  getAdminStats,
  getAdminModels,
  getAdminConfig,
  updateAdminConfig,
  getPipelineErrors,
} from '../lib/api.ts'
import type {
  AdminStats,
  AdminModels,
  AdminConfig,
  ModelHealth,
  AgentEvent,
  Pipeline,
} from '../types/pipeline.ts'
import { listPipelines } from '../lib/api.ts'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return `${mins}m ${secs}s`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ${mins % 60}m`
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function shortModelName(id: string): string {
  if (id.includes('sonnet')) return 'Sonnet 4.5'
  if (id.includes('haiku')) return 'Haiku 4.5'
  if (id.includes('qwen')) return 'Qwen 32B (local)'
  return id.split('/').pop() ?? id
}

const REFRESH_MS = 15_000

// ---------------------------------------------------------------------------
// Stat Card
// ---------------------------------------------------------------------------

function StatCard({ icon, label, value, sub, color }: {
  icon: React.ReactNode
  label: string
  value: string | number
  sub?: string
  color: string
}) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className={clsx('p-2 rounded-md', color)}>{icon}</div>
        <span className="text-sm text-slate-400">{label}</span>
      </div>
      <p className="text-2xl font-semibold text-slate-100">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Model Health Table
// ---------------------------------------------------------------------------

function ModelHealthTable({ models }: { models: Record<string, ModelHealth> }) {
  const entries = Object.entries(models)
  if (entries.length === 0) {
    return <p className="text-sm text-slate-500 p-4">No model data available yet.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700 text-slate-400 text-left">
            <th className="py-2 px-3 font-medium">Model</th>
            <th className="py-2 px-3 font-medium">Status</th>
            <th className="py-2 px-3 font-medium text-right">Avg Latency</th>
            <th className="py-2 px-3 font-medium text-right">Error Rate</th>
            <th className="py-2 px-3 font-medium text-right">Total Calls</th>
            <th className="py-2 px-3 font-medium text-right">Tokens Used</th>
            <th className="py-2 px-3 font-medium text-right">Pricing (in/out)</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([id, m]) => (
            <tr key={id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
              <td className="py-2.5 px-3">
                <div className="flex items-center gap-2">
                  {m.is_local
                    ? <Cpu className="w-3.5 h-3.5 text-purple-400" />
                    : <Server className="w-3.5 h-3.5 text-blue-400" />}
                  <span className="text-slate-200">{shortModelName(id)}</span>
                </div>
              </td>
              <td className="py-2.5 px-3">
                {m.available
                  ? <span className="inline-flex items-center gap-1 text-emerald-400 text-xs">
                      <CheckCircle className="w-3 h-3" /> Available
                    </span>
                  : <span className="inline-flex items-center gap-1 text-red-400 text-xs">
                      <XCircle className="w-3 h-3" /> Offline
                    </span>}
              </td>
              <td className="py-2.5 px-3 text-right text-slate-300">
                {m.avg_latency_ms > 0 ? `${Math.round(m.avg_latency_ms)}ms` : '—'}
              </td>
              <td className={clsx(
                'py-2.5 px-3 text-right',
                m.error_rate > 10 ? 'text-red-400' : m.error_rate > 5 ? 'text-amber-400' : 'text-slate-300',
              )}>
                {m.error_rate > 0 ? `${m.error_rate}%` : '0%'}
              </td>
              <td className="py-2.5 px-3 text-right text-slate-300">
                {m.total_calls.toLocaleString()}
              </td>
              <td className="py-2.5 px-3 text-right text-slate-300">
                {formatTokens(m.total_input_tokens + m.total_output_tokens)}
              </td>
              <td className="py-2.5 px-3 text-right text-slate-400 text-xs">
                ${m.pricing_input_per_mtok} / ${m.pricing_output_per_mtok}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Config Form
// ---------------------------------------------------------------------------

function ConfigForm({ config, onSave }: {
  config: AdminConfig
  onSave: (c: Partial<AdminConfig>) => Promise<void>
}) {
  const [engineers, setEngineers] = useState(config.max_concurrent_engineers)
  const [qaCycles, setQaCycles] = useState(config.max_qa_cycles)
  const [autoMerge, setAutoMerge] = useState(config.auto_merge)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setEngineers(config.max_concurrent_engineers)
    setQaCycles(config.max_qa_cycles)
    setAutoMerge(config.auto_merge)
  }, [config])

  async function handleSave() {
    setSaving(true)
    try {
      await onSave({
        max_concurrent_engineers: engineers,
        max_qa_cycles: qaCycles,
        auto_merge: autoMerge,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <label className="block">
          <span className="text-xs text-slate-400 mb-1 block">Max Concurrent Engineers</span>
          <input
            type="number"
            min={1}
            max={16}
            value={engineers}
            onChange={e => setEngineers(Number(e.target.value))}
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2
                       text-slate-200 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </label>
        <label className="block">
          <span className="text-xs text-slate-400 mb-1 block">Max QA Cycles</span>
          <input
            type="number"
            min={1}
            max={10}
            value={qaCycles}
            onChange={e => setQaCycles(Number(e.target.value))}
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2
                       text-slate-200 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </label>
        <label className="flex items-center gap-2 pt-5">
          <input
            type="checkbox"
            checked={autoMerge}
            onChange={e => setAutoMerge(e.target.checked)}
            className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-sm text-slate-300">Auto-merge on QA pass</span>
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500
                     disabled:opacity-50 text-white text-sm font-medium px-4 py-2
                     rounded transition-colors"
        >
          <Save className="w-3.5 h-3.5" />
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
        {saved && (
          <span className="text-emerald-400 text-sm flex items-center gap-1">
            <CheckCircle className="w-3.5 h-3.5" /> Saved
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recent Errors List
// ---------------------------------------------------------------------------

function RecentErrorsList({ errors }: { errors: AgentEvent[] }) {
  if (errors.length === 0) {
    return <p className="text-sm text-slate-500 p-4">No recent errors.</p>
  }

  return (
    <div className="space-y-2 max-h-96 overflow-y-auto">
      {errors.map(evt => {
        const p = evt.payload ?? {}
        return (
          <div
            key={evt.id}
            className="border-l-2 border-red-500/60 bg-slate-800/40 rounded-r px-3 py-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-xs font-medium text-red-400">
                    {(p.error_type as string) ?? evt.event_type}
                  </span>
                  {evt.stage && (
                    <span className="text-xs text-slate-500">
                      in {evt.stage}
                    </span>
                  )}
                  {p.attempt != null && (
                    <span className="text-xs text-slate-500">
                      attempt {String(p.attempt)}/{String(p.max_retries)}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 truncate">
                  {(p.message as string) ?? String(evt.event_type)}
                </p>
              </div>
              <div className="text-right shrink-0">
                <Link
                  to={`/pipeline/${evt.pipeline_id}`}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  {evt.pipeline_id.slice(0, 8)}
                </Link>
                <p className="text-xs text-slate-600">{relativeTime(evt.created_at)}</p>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Admin Page
// ---------------------------------------------------------------------------

export default function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [models, setModels] = useState<AdminModels | null>(null)
  const [config, setConfig] = useState<AdminConfig | null>(null)
  const [recentErrors, setRecentErrors] = useState<AgentEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      const [s, m, c, pipelines] = await Promise.all([
        getAdminStats(),
        getAdminModels(),
        getAdminConfig(),
        listPipelines(),
      ])
      setStats(s)
      setModels(m)
      setConfig(c)

      // Gather recent errors from the most recent pipelines
      const recent = pipelines
        .filter((p: Pipeline) => p.status === 'failed' || p.status === 'running')
        .slice(0, 5)

      const errorLists = await Promise.all(
        recent.map((p: Pipeline) =>
          getPipelineErrors(p.pipeline_id).catch(() => []),
        ),
      )
      const allErrors = errorLists
        .flat()
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
        .slice(0, 20)
      setRecentErrors(allErrors)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load admin data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, REFRESH_MS)
    return () => clearInterval(interval)
  }, [loadData])

  async function handleConfigSave(updated: Partial<AdminConfig>) {
    await updateAdminConfig(updated)
    const fresh = await getAdminConfig()
    setConfig(fresh)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex items-center gap-3 text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          Loading admin data...
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800/80 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="text-slate-400 hover:text-slate-200 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <h1 className="text-lg font-semibold flex items-center gap-2">
              <Zap className="w-5 h-5 text-amber-400" />
              Forge Admin
            </h1>
          </div>
          <button
            onClick={loadData}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto px-4 pt-4">
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Stats Cards */}
        {stats && (
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
              System Overview
            </h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <StatCard
                icon={<Activity className="w-4 h-4" />}
                label="Total Pipelines"
                value={stats.total_pipelines}
                sub={`${stats.succeeded} succeeded, ${stats.failed} failed`}
                color="bg-blue-900/40 text-blue-400"
              />
              <StatCard
                icon={<CheckCircle className="w-4 h-4" />}
                label="Success Rate"
                value={`${stats.success_rate}%`}
                sub={`Avg duration: ${formatDuration(stats.avg_duration_seconds)}`}
                color={
                  stats.success_rate >= 80
                    ? 'bg-emerald-900/40 text-emerald-400'
                    : stats.success_rate >= 50
                      ? 'bg-amber-900/40 text-amber-400'
                      : 'bg-red-900/40 text-red-400'
                }
              />
              <StatCard
                icon={<DollarSign className="w-4 h-4" />}
                label="Total Cost"
                value={`$${stats.total_cost_usd.toFixed(2)}`}
                sub={`Avg $${stats.avg_cost_usd.toFixed(2)} per pipeline`}
                color="bg-purple-900/40 text-purple-400"
              />
              <StatCard
                icon={<AlertTriangle className="w-4 h-4" />}
                label="Failure Hotspots"
                value={
                  stats.failure_stages.length > 0
                    ? stats.failure_stages[0].stage.replace(/_/g, ' ')
                    : 'None'
                }
                sub={
                  stats.failure_stages.length > 0
                    ? `${stats.failure_stages[0].count} failures`
                    : 'No failures recorded'
                }
                color="bg-red-900/40 text-red-400"
              />
            </div>
          </section>
        )}

        {/* Model Health */}
        {models && (
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
              Model Health
            </h2>
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 overflow-hidden">
              <ModelHealthTable models={models.models} />
            </div>
          </section>
        )}

        {/* Pipeline Configuration */}
        {config && (
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
              Pipeline Configuration
            </h2>
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-5">
              <p className="text-xs text-slate-500 mb-4">
                Changes take effect on the next pipeline started. Running pipelines are not affected.
              </p>
              <ConfigForm config={config} onSave={handleConfigSave} />
            </div>
          </section>
        )}

        {/* Recent Errors */}
        <section>
          <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
            Recent Errors
          </h2>
          <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4">
            <RecentErrorsList errors={recentErrors} />
          </div>
        </section>

        {/* Model Usage Breakdown */}
        {stats && Object.keys(stats.model_usage).length > 0 && (
          <section>
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
              Model Usage
            </h2>
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-5">
              <div className="space-y-3">
                {Object.entries(stats.model_usage).map(([model, info]) => (
                  <div key={model} className="flex items-center gap-3">
                    <span className="text-sm text-slate-300 w-32 truncate">
                      {shortModelName(model)}
                    </span>
                    <div className="flex-1 bg-slate-700 rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-blue-500 h-full rounded-full transition-all"
                        style={{ width: `${Math.min(info.percentage, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-400 w-20 text-right">
                      {info.percentage}% ({info.calls})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
