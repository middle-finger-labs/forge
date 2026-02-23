import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Activity, Wifi, WifiOff } from 'lucide-react'
import clsx from 'clsx'
import { getPipelineState } from '../lib/api.ts'
import { useWebSocket } from '../hooks/useWebSocket.ts'
import type { PipelineState } from '../types/pipeline.ts'

export default function PipelineDetail() {
  const { id } = useParams<{ id: string }>()
  const [state, setState] = useState<PipelineState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { events, connected } = useWebSocket(id)

  useEffect(() => {
    if (!id) return
    getPipelineState(id)
      .then(setState)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-500">
        <Activity className="mr-2 h-5 w-5 animate-spin" />
        Loading pipeline...
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-red-300">
          {error}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-slate-400 hover:text-slate-200">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <h2 className="font-mono text-lg text-slate-200">{id}</h2>
          {state && (
            <span className="rounded bg-cyan-900 px-2 py-0.5 text-xs font-medium text-cyan-300">
              {state.current_stage}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-sm">
          {connected ? (
            <span className="flex items-center gap-1 text-emerald-400">
              <Wifi className="h-4 w-4" /> Live
            </span>
          ) : (
            <span className="flex items-center gap-1 text-slate-500">
              <WifiOff className="h-4 w-4" /> Disconnected
            </span>
          )}
        </div>
      </div>

      {/* State overview */}
      {state && (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-sm text-slate-500">Stage</div>
            <div className="mt-1 text-lg font-medium text-slate-200">
              {state.current_stage}
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-sm text-slate-500">Cost</div>
            <div className="mt-1 text-lg font-medium text-slate-200">
              ${state.total_cost_usd.toFixed(4)}
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-sm text-slate-500">Pending Approval</div>
            <div className={clsx(
              'mt-1 text-lg font-medium',
              state.pending_approval ? 'text-amber-400' : 'text-slate-500',
            )}>
              {state.pending_approval ?? 'None'}
            </div>
          </div>
        </div>
      )}

      {/* Live events */}
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-400">
          Live Events ({events.length})
        </h3>
        {events.length === 0 ? (
          <div className="py-4 text-center text-sm text-slate-600">
            Waiting for events...
          </div>
        ) : (
          <div className="max-h-80 space-y-1 overflow-y-auto">
            {events.slice(-50).reverse().map((evt, i) => (
              <div
                key={`${evt.event_type}-${evt.timestamp ?? i}`}
                className="flex items-baseline gap-2 rounded px-2 py-1 text-sm hover:bg-slate-800"
              >
                <span className="shrink-0 font-mono text-xs text-slate-600">
                  {evt.timestamp
                    ? new Date(evt.timestamp).toLocaleTimeString()
                    : ''}
                </span>
                <span className="font-medium text-cyan-400">
                  {evt.event_type}
                </span>
                {evt.stage && (
                  <span className="text-slate-500">{evt.stage}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
