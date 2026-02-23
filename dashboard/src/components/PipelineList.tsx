import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Clock, DollarSign } from 'lucide-react'
import clsx from 'clsx'
import { listPipelines } from '../lib/api.ts'
import type { Pipeline } from '../types/pipeline.ts'

const stageBadge: Record<string, string> = {
  intake: 'bg-slate-700 text-slate-300',
  business_analysis: 'bg-blue-900 text-blue-300',
  research: 'bg-purple-900 text-purple-300',
  architecture: 'bg-indigo-900 text-indigo-300',
  task_decomposition: 'bg-amber-900 text-amber-300',
  coding: 'bg-cyan-900 text-cyan-300',
  qa_review: 'bg-yellow-900 text-yellow-300',
  merge: 'bg-teal-900 text-teal-300',
  complete: 'bg-emerald-900 text-emerald-300',
  failed: 'bg-red-900 text-red-300',
}

export default function PipelineList() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listPipelines()
      .then(setPipelines)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-500">
        <Activity className="mr-2 h-5 w-5 animate-spin" />
        Loading pipelines...
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-red-300">
        Failed to load pipelines: {error}
      </div>
    )
  }

  if (pipelines.length === 0) {
    return (
      <div className="py-20 text-center text-slate-500">
        No pipelines yet. Start one from the API.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <h2 className="mb-4 text-xl font-semibold text-slate-200">Pipelines</h2>
      {pipelines.map((p) => (
        <Link
          key={p.pipeline_id}
          to={`/pipeline/${p.pipeline_id}`}
          className="block rounded-lg border border-slate-800 bg-slate-900 p-4 transition hover:border-slate-600"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm text-slate-400">
                {p.pipeline_id}
              </span>
              <span
                className={clsx(
                  'rounded px-2 py-0.5 text-xs font-medium',
                  stageBadge[p.current_stage] ?? 'bg-slate-700 text-slate-300',
                )}
              >
                {p.current_stage}
              </span>
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-400">
              <span className="flex items-center gap-1">
                <DollarSign className="h-3.5 w-3.5" />
                {p.total_cost_usd.toFixed(4)}
              </span>
              <span className="flex items-center gap-1">
                <Clock className="h-3.5 w-3.5" />
                {new Date(p.created_at).toLocaleString()}
              </span>
            </div>
          </div>
        </Link>
      ))}
    </div>
  )
}
