import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, Clock, DollarSign, GitBranch, Plus, Settings, X, Zap } from 'lucide-react'
import clsx from 'clsx'
import { listPipelines, startPipeline } from '../lib/api.ts'
import type { Pipeline } from '../types/pipeline.ts'
import OrgSwitcher from '../components/OrgSwitcher.tsx'
import UserMenu from '../components/UserMenu.tsx'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

const statusColor: Record<string, string> = {
  complete: 'bg-emerald-900/60 text-emerald-300 ring-emerald-700/40',
  completed: 'bg-emerald-900/60 text-emerald-300 ring-emerald-700/40',
  running: 'bg-blue-900/60 text-blue-300 ring-blue-700/40',
  active: 'bg-blue-900/60 text-blue-300 ring-blue-700/40',
  awaiting_approval: 'bg-amber-900/60 text-amber-300 ring-amber-700/40',
  pending_approval: 'bg-amber-900/60 text-amber-300 ring-amber-700/40',
  failed: 'bg-red-900/60 text-red-300 ring-red-700/40',
  error: 'bg-red-900/60 text-red-300 ring-red-700/40',
  pending: 'bg-slate-700/60 text-slate-300 ring-slate-600/40',
}

const stageBadge: Record<string, string> = {
  intake: 'text-slate-400',
  business_analysis: 'text-blue-400',
  research: 'text-purple-400',
  architecture: 'text-indigo-400',
  task_decomposition: 'text-amber-400',
  coding: 'text-cyan-400',
  qa_review: 'text-yellow-400',
  merge: 'text-teal-400',
  complete: 'text-emerald-400',
  failed: 'text-red-400',
}

const REFRESH_INTERVAL_MS = 10_000

// ---------------------------------------------------------------------------
// New Pipeline Modal
// ---------------------------------------------------------------------------

function NewPipelineModal({ onClose, onCreated }: {
  onClose: () => void
  onCreated: (pipelineId: string) => void
}) {
  const [businessSpec, setBusinessSpec] = useState('')
  const [projectName, setProjectName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [identity, setIdentity] = useState('')
  const [issueNumber, setIssueNumber] = useState('')
  const [prStrategy, setPrStrategy] = useState<'single_pr' | 'pr_per_ticket' | 'direct_push'>('single_pr')
  const [showGitHub, setShowGitHub] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!businessSpec.trim()) return

    setSubmitting(true)
    setError(null)

    try {
      const result = await startPipeline({
        business_spec: businessSpec.trim(),
        project_name: projectName.trim() || undefined,
        repo_url: repoUrl.trim() || undefined,
        identity: identity.trim() || undefined,
        issue_number: issueNumber ? Number(issueNumber) : undefined,
        pr_strategy: repoUrl.trim() ? prStrategy : undefined,
      })
      onCreated(result.pipeline_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start pipeline')
      setSubmitting(false)
    }
  }

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === backdropRef.current) onClose()
  }

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    >
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        {/* Modal header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <h3 className="text-lg font-semibold text-slate-100">New Pipeline</h3>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal body */}
        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-5">
          <div>
            <label htmlFor="project-name" className="mb-1.5 block text-sm font-medium text-slate-300">
              Project Name
            </label>
            <input
              id="project-name"
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="my-project"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
            />
          </div>

          <div>
            <label htmlFor="business-spec" className="mb-1.5 block text-sm font-medium text-slate-300">
              Business Spec <span className="text-red-400">*</span>
            </label>
            <textarea
              id="business-spec"
              value={businessSpec}
              onChange={(e) => setBusinessSpec(e.target.value)}
              placeholder="Describe what you want to build..."
              rows={6}
              className="w-full resize-y rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
            />
          </div>

          {/* GitHub integration (collapsible) */}
          <div className="rounded-lg border border-slate-700/50 bg-slate-800/30">
            <button
              type="button"
              onClick={() => setShowGitHub(!showGitHub)}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-400 hover:text-slate-300"
            >
              <GitBranch className="h-3.5 w-3.5" />
              GitHub Integration
              <span className="ml-auto text-xs">{showGitHub ? '▾' : '▸'}</span>
            </button>
            {showGitHub && (
              <div className="space-y-3 border-t border-slate-700/50 px-3 pb-3 pt-2">
                <div>
                  <label htmlFor="repo-url" className="mb-1 block text-xs font-medium text-slate-400">
                    GitHub Repo URL
                  </label>
                  <input
                    id="repo-url"
                    type="text"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    placeholder="git@github.com:org/repo.git"
                    className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 font-mono text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="identity" className="mb-1 block text-xs font-medium text-slate-400">
                      Identity
                    </label>
                    <input
                      id="identity"
                      type="text"
                      value={identity}
                      onChange={(e) => setIdentity(e.target.value)}
                      placeholder="default"
                      className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
                    />
                  </div>
                  <div>
                    <label htmlFor="issue-number" className="mb-1 block text-xs font-medium text-slate-400">
                      Issue #
                    </label>
                    <input
                      id="issue-number"
                      type="number"
                      value={issueNumber}
                      onChange={(e) => setIssueNumber(e.target.value)}
                      placeholder="42"
                      className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
                    />
                  </div>
                </div>
                {repoUrl.trim() && (
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">
                      PR Strategy
                    </label>
                    <div className="flex gap-3">
                      {([
                        ['single_pr', 'Single PR'],
                        ['pr_per_ticket', 'PR per ticket'],
                        ['direct_push', 'Direct push'],
                      ] as const).map(([value, label]) => (
                        <label key={value} className="flex items-center gap-1.5 text-sm text-slate-300">
                          <input
                            type="radio"
                            name="pr-strategy"
                            value={value}
                            checked={prStrategy === value}
                            onChange={() => setPrStrategy(value)}
                            className="accent-cyan-500"
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm text-slate-400 transition hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !businessSpec.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <Activity className="h-4 w-4 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Zap className="h-4 w-4" />
                  Start Pipeline
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function PipelineListPage() {
  const navigate = useNavigate()
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  const fetchPipelines = useCallback(() => {
    listPipelines()
      .then(setPipelines)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  // Initial fetch + auto-refresh every 10s
  useEffect(() => {
    fetchPipelines()
    const timer = setInterval(fetchPipelines, REFRESH_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [fetchPipelines])

  function handleCreated(pipelineId: string) {
    setShowModal(false)
    navigate(`/pipeline/${pipelineId}`)
  }

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Zap className="h-5 w-5 text-cyan-400" />
            <span className="text-lg font-bold tracking-tight text-slate-100">Forge</span>
          </div>
          <div className="flex items-center gap-3">
            <OrgSwitcher />
            <Link
              to="/settings"
              className="rounded-lg border border-slate-700 p-2 text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </Link>
            <button
              onClick={() => setShowModal(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-cyan-500"
            >
              <Plus className="h-4 w-4" />
              New Pipeline
            </button>
            <UserMenu />
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="mx-auto max-w-5xl px-6 py-8">
        {loading ? (
          <div className="flex items-center justify-center py-20 text-slate-500">
            <Activity className="mr-2 h-5 w-5 animate-spin" />
            Loading pipelines...
          </div>
        ) : error ? (
          <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-red-300">
            Failed to load pipelines: {error}
          </div>
        ) : pipelines.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="rounded-full bg-slate-800 p-4">
              <Zap className="h-8 w-8 text-slate-600" />
            </div>
            <h3 className="mt-4 text-lg font-medium text-slate-300">No pipelines yet</h3>
            <p className="mt-1 text-sm text-slate-500">
              Create your first pipeline to get started.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="mt-6 inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-cyan-500"
            >
              <Plus className="h-4 w-4" />
              New Pipeline
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {/* Column labels */}
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-4 pb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
              <span>Pipeline</span>
              <span className="w-28 text-center">Status</span>
              <span className="w-32 text-center">Stage</span>
              <span className="w-24 text-right">Cost</span>
              <span className="w-24 text-right">Created</span>
            </div>

            {/* Rows */}
            {pipelines.map((p) => (
              <button
                key={p.pipeline_id}
                onClick={() => navigate(`/pipeline/${p.pipeline_id}`)}
                className="grid w-full grid-cols-[1fr_auto_auto_auto_auto] items-center gap-4 rounded-lg border border-slate-800 bg-slate-900 px-4 py-3.5 text-left transition hover:border-slate-600 hover:bg-slate-800/60"
              >
                {/* Pipeline ID */}
                <span className="truncate font-mono text-sm text-slate-300">
                  {p.pipeline_id}
                </span>

                {/* Status badge */}
                <span className="w-28 text-center">
                  <span
                    className={clsx(
                      'inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset',
                      statusColor[p.status] ?? 'bg-slate-700/60 text-slate-300 ring-slate-600/40',
                    )}
                  >
                    {p.status}
                  </span>
                </span>

                {/* Current stage */}
                <span className="w-32 text-center">
                  <span
                    className={clsx(
                      'text-xs font-medium',
                      stageBadge[p.current_stage] ?? 'text-slate-400',
                    )}
                  >
                    {p.current_stage}
                  </span>
                </span>

                {/* Cost */}
                <span className="flex w-24 items-center justify-end gap-1 font-mono text-xs text-slate-400">
                  <DollarSign className="h-3 w-3" />
                  {p.total_cost_usd.toFixed(4)}
                </span>

                {/* Created at */}
                <span className="flex w-24 items-center justify-end gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" />
                  {relativeTime(p.created_at)}
                </span>
              </button>
            ))}
          </div>
        )}
      </main>

      {/* Modal */}
      {showModal && (
        <NewPipelineModal
          onClose={() => setShowModal(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
