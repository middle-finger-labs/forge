import { useState } from 'react'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Code2,
  Eye,
  FileCode2,
  FileText,
  FolderTree,
  Layers,
  LayoutList,
  ListChecks,
  Server,
  Tag,
  X,
  XCircle,
} from 'lucide-react'
import clsx from 'clsx'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ArtifactKind =
  | 'product_spec'
  | 'enriched_spec'
  | 'tech_spec'
  | 'prd_board'
  | 'code_artifact'
  | 'qa_review'

interface ArtifactViewerProps {
  kind: ArtifactKind
  data: Record<string, unknown>
  title?: string
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function str(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {}
}

function stageLabel(stage: string): string {
  return stage.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export const KIND_TITLES: Record<ArtifactKind, string> = {
  product_spec: 'Product Spec',
  enriched_spec: 'Enriched Spec',
  tech_spec: 'Tech Spec',
  prd_board: 'PRD Board',
  code_artifact: 'Code Artifact',
  qa_review: 'QA Review',
}

// ---------------------------------------------------------------------------
// Severity / verdict styles
// ---------------------------------------------------------------------------

const VERDICT_STYLE: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
  pass:     { bg: 'bg-emerald-900/50', text: 'text-emerald-300', icon: <CheckCircle2 className="h-5 w-5" /> },
  passed:   { bg: 'bg-emerald-900/50', text: 'text-emerald-300', icon: <CheckCircle2 className="h-5 w-5" /> },
  approved: { bg: 'bg-emerald-900/50', text: 'text-emerald-300', icon: <CheckCircle2 className="h-5 w-5" /> },
  fail:     { bg: 'bg-red-900/50',     text: 'text-red-300',     icon: <XCircle className="h-5 w-5" /> },
  failed:   { bg: 'bg-red-900/50',     text: 'text-red-300',     icon: <XCircle className="h-5 w-5" /> },
  rejected: { bg: 'bg-red-900/50',     text: 'text-red-300',     icon: <XCircle className="h-5 w-5" /> },
  revise:   { bg: 'bg-amber-900/50',   text: 'text-amber-300',   icon: <AlertTriangle className="h-5 w-5" /> },
  needs_revision: { bg: 'bg-amber-900/50', text: 'text-amber-300', icon: <AlertTriangle className="h-5 w-5" /> },
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'text-red-400 border-red-800',
  high:     'text-red-400 border-red-800',
  major:    'text-orange-400 border-orange-800',
  medium:   'text-amber-400 border-amber-800',
  minor:    'text-yellow-400 border-yellow-800',
  low:      'text-slate-400 border-slate-700',
  info:     'text-cyan-400 border-cyan-800',
}

const PRIORITY_STYLE: Record<string, string> = {
  critical: 'bg-red-900/50 text-red-300',
  high:     'bg-orange-900/50 text-orange-300',
  medium:   'bg-amber-900/50 text-amber-300',
  low:      'bg-slate-700/50 text-slate-400',
}

const TICKET_STATUS: Record<string, string> = {
  completed: 'bg-emerald-900/50 text-emerald-300',
  complete:  'bg-emerald-900/50 text-emerald-300',
  running:   'bg-blue-900/50 text-blue-300',
  active:    'bg-blue-900/50 text-blue-300',
  failed:    'bg-red-900/50 text-red-300',
  pending:   'bg-slate-700/50 text-slate-400',
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
        {icon}
        {title}
      </h4>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ProductSpec view
// ---------------------------------------------------------------------------

function ProductSpecView({ data }: { data: Record<string, unknown> }) {
  const stories = arr(data.user_stories ?? data.userStories)
  const metrics = arr(data.success_metrics ?? data.successMetrics)
  const questions = arr(data.open_questions ?? data.openQuestions)

  return (
    <>
      {/* Overview */}
      {(data.product_name || data.name) && (
        <Section title="Product" icon={<Layers className="h-3.5 w-3.5" />}>
          <div className="text-base font-semibold text-slate-200">
            {str(data.product_name ?? data.name)}
          </div>
          {!!data.vision && (
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{str(data.vision)}</p>
          )}
        </Section>
      )}

      {/* User stories */}
      {stories.length > 0 && (
        <Section title={`User Stories (${stories.length})`} icon={<LayoutList className="h-3.5 w-3.5" />}>
          <div className="space-y-2">
            {stories.map((s, i) => {
              const story = obj(s)
              return (
                <div key={i} className="rounded-lg border border-slate-800 bg-slate-800/40 p-3">
                  <div className="text-sm font-medium text-slate-200">
                    {str(story.title ?? story.name ?? `Story ${i + 1}`)}
                  </div>
                  {!!story.description && (
                    <p className="mt-1 text-xs text-slate-400">{str(story.description)}</p>
                  )}
                  {arr(story.acceptance_criteria ?? story.acceptanceCriteria).length > 0 && (
                    <ul className="mt-2 space-y-0.5">
                      {arr(story.acceptance_criteria ?? story.acceptanceCriteria).map((c, j) => (
                        <li key={j} className="flex items-start gap-1.5 text-xs text-slate-500">
                          <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" />
                          {str(c)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {/* Success metrics */}
      {metrics.length > 0 && (
        <Section title="Success Metrics" icon={<CheckCircle2 className="h-3.5 w-3.5" />}>
          <ul className="space-y-1">
            {metrics.map((m, i) => (
              <li key={i} className="text-xs text-slate-400">
                {typeof m === 'string' ? m : str(obj(m).metric ?? obj(m).name ?? m)}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Open questions */}
      {questions.length > 0 && (
        <Section title="Open Questions" icon={<AlertTriangle className="h-3.5 w-3.5" />}>
          <ul className="space-y-1">
            {questions.map((q, i) => (
              <li key={i} className="text-xs text-amber-400/80">{str(q)}</li>
            ))}
          </ul>
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// TechSpec view
// ---------------------------------------------------------------------------

function TechSpecView({ data }: { data: Record<string, unknown> }) {
  const stack = obj(data.tech_stack ?? data.techStack)
  const services = arr(data.services ?? data.components)
  const fileStructure = data.file_structure ?? data.fileStructure

  return (
    <>
      {/* Architecture overview */}
      {data.architecture_overview && (
        <Section title="Architecture Overview" icon={<Layers className="h-3.5 w-3.5" />}>
          <p className="text-sm leading-relaxed text-slate-300">{str(data.architecture_overview)}</p>
        </Section>
      )}

      {/* Tech stack table */}
      {Object.keys(stack).length > 0 && (
        <Section title="Tech Stack" icon={<Server className="h-3.5 w-3.5" />}>
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-800/60">
                  <th className="px-3 py-1.5 text-left font-medium text-slate-400">Category</th>
                  <th className="px-3 py-1.5 text-left font-medium text-slate-400">Technology</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(stack).map(([key, val]) => (
                  <tr key={key} className="border-b border-slate-800/50 last:border-0">
                    <td className="px-3 py-1.5 font-medium text-slate-300">{stageLabel(key)}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-400">{str(val)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {/* Services */}
      {services.length > 0 && (
        <Section title={`Services (${services.length})`} icon={<Server className="h-3.5 w-3.5" />}>
          <div className="space-y-2">
            {services.map((s, i) => {
              const svc = obj(s)
              const endpoints = arr(svc.endpoints ?? svc.routes)
              const models = arr(svc.models ?? svc.entities)
              return (
                <div key={i} className="rounded-lg border border-slate-800 bg-slate-800/40 p-3">
                  <div className="text-sm font-semibold text-slate-200">
                    {str(svc.name ?? `Service ${i + 1}`)}
                  </div>
                  {!!svc.description && (
                    <p className="mt-0.5 text-xs text-slate-400">{str(svc.description)}</p>
                  )}
                  {endpoints.length > 0 && (
                    <div className="mt-2">
                      <div className="mb-1 text-[10px] font-semibold uppercase text-slate-500">Endpoints</div>
                      {endpoints.map((ep, j) => {
                        const e = obj(ep)
                        return (
                          <div key={j} className="flex items-center gap-2 text-xs">
                            <span className="font-mono text-cyan-400">{str(e.method ?? 'GET')}</span>
                            <span className="font-mono text-slate-300">{str(e.path ?? e.route ?? ep)}</span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                  {models.length > 0 && (
                    <div className="mt-2">
                      <div className="mb-1 text-[10px] font-semibold uppercase text-slate-500">Models</div>
                      <div className="flex flex-wrap gap-1.5">
                        {models.map((m, j) => (
                          <span key={j} className="rounded bg-slate-700 px-1.5 py-0.5 font-mono text-[11px] text-slate-300">
                            {str(obj(m).name ?? m)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {/* File structure */}
      {fileStructure && (
        <Section title="File Structure" icon={<FolderTree className="h-3.5 w-3.5" />}>
          <pre className="max-h-64 overflow-auto rounded-lg border border-slate-800 bg-[#0c0e14] p-3 font-mono text-[11px] leading-relaxed text-slate-300">
            {typeof fileStructure === 'string'
              ? fileStructure
              : JSON.stringify(fileStructure, null, 2)}
          </pre>
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// PRDBoard view
// ---------------------------------------------------------------------------

function PRDBoardView({ data }: { data: Record<string, unknown> }) {
  const execOrder = arr(data.execution_order ?? data.executionOrder)
  const tickets = obj(data.tickets ?? {})
  // Flatten: tickets might be at top-level or nested by group
  const allTickets: Record<string, unknown>[] = Object.values(tickets).map((t) => obj(t))

  return (
    <>
      {execOrder.length > 0 && execOrder.map((group, gi) => {
        const ticketKeys = arr(group)
        return (
          <Section
            key={gi}
            title={`Group ${gi + 1} (${ticketKeys.length} tickets)`}
            icon={<LayoutList className="h-3.5 w-3.5" />}
          >
            <div className="space-y-2">
              {ticketKeys.map((key, ti) => {
                const k = str(key)
                const ticket = allTickets.find(
                  (t) => str(t.ticket_key ?? t.key ?? t.id) === k,
                ) ?? obj(tickets[k])
                const priority = str(ticket.priority ?? '').toLowerCase()
                const status = str(ticket.status ?? 'pending').toLowerCase()
                const filesToCreate = arr(ticket.files_to_create ?? ticket.filesToCreate)
                const filesToModify = arr(ticket.files_to_modify ?? ticket.filesToModify)
                const deps = arr(ticket.dependencies ?? ticket.depends_on)

                return (
                  <div key={ti} className="rounded-lg border border-slate-800 bg-slate-800/40 p-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-cyan-400">{k}</span>
                      <span className={clsx(
                        'rounded px-1.5 py-px text-[10px] font-bold uppercase',
                        TICKET_STATUS[status] ?? 'bg-slate-700/50 text-slate-400',
                      )}>
                        {status}
                      </span>
                      {priority && (
                        <span className={clsx(
                          'rounded px-1.5 py-px text-[10px] font-bold uppercase',
                          PRIORITY_STYLE[priority] ?? 'bg-slate-700/50 text-slate-400',
                        )}>
                          {priority}
                        </span>
                      )}
                    </div>
                    {!!ticket.title && (
                      <div className="mt-1 text-sm font-medium text-slate-200">{str(ticket.title)}</div>
                    )}
                    {!!ticket.description && (
                      <p className="mt-0.5 text-xs text-slate-400">{str(ticket.description)}</p>
                    )}
                    {(filesToCreate.length > 0 || filesToModify.length > 0) && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {filesToCreate.map((f, fi) => (
                          <span key={`c-${fi}`} className="inline-flex items-center gap-1 rounded bg-emerald-950/40 px-1.5 py-0.5 font-mono text-[10px] text-emerald-400">
                            <FileCode2 className="h-2.5 w-2.5" /> {str(f)}
                          </span>
                        ))}
                        {filesToModify.map((f, fi) => (
                          <span key={`m-${fi}`} className="inline-flex items-center gap-1 rounded bg-amber-950/40 px-1.5 py-0.5 font-mono text-[10px] text-amber-400">
                            <FileText className="h-2.5 w-2.5" /> {str(f)}
                          </span>
                        ))}
                      </div>
                    )}
                    {deps.length > 0 && (
                      <div className="mt-1.5 flex items-center gap-1 text-[10px] text-slate-600">
                        <Tag className="h-2.5 w-2.5" />
                        depends on: {deps.map(str).join(', ')}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </Section>
        )
      })}

      {/* Fallback if no execution_order but has tickets */}
      {execOrder.length === 0 && allTickets.length > 0 && (
        <Section title={`Tickets (${allTickets.length})`} icon={<LayoutList className="h-3.5 w-3.5" />}>
          <pre className="rounded-lg border border-slate-800 bg-[#0c0e14] p-3 font-mono text-[11px] text-slate-300">
            {JSON.stringify(data, null, 2)}
          </pre>
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// CodeArtifact view
// ---------------------------------------------------------------------------

function CodeArtifactView({ data }: { data: Record<string, unknown> }) {
  const files = arr(data.files ?? data.created_files ?? data.changes)

  return (
    <>
      {data.ticket_key && (
        <Section title="Ticket" icon={<Tag className="h-3.5 w-3.5" />}>
          <span className="font-mono text-sm text-cyan-400">{str(data.ticket_key)}</span>
          {!!data.branch_name && (
            <span className="ml-3 text-xs text-slate-500">
              branch: <span className="font-mono text-slate-400">{str(data.branch_name)}</span>
            </span>
          )}
        </Section>
      )}

      {files.length > 0 && (
        <Section title={`Files (${files.length})`} icon={<FileCode2 className="h-3.5 w-3.5" />}>
          <div className="space-y-1">
            {files.map((f, i) => {
              const file = obj(f)
              return (
                <div key={i} className="flex items-center gap-2 rounded border border-slate-800 bg-slate-800/40 px-3 py-1.5">
                  <Code2 className="h-3 w-3 shrink-0 text-cyan-500" />
                  <span className="min-w-0 truncate font-mono text-xs text-slate-300">
                    {str(file.path ?? file.filename ?? f)}
                  </span>
                  {!!file.action && (
                    <span className={clsx(
                      'ml-auto shrink-0 rounded px-1.5 py-px text-[10px] font-bold uppercase',
                      file.action === 'create' ? 'bg-emerald-900/50 text-emerald-400'
                        : file.action === 'modify' ? 'bg-amber-900/50 text-amber-400'
                        : 'bg-slate-700/50 text-slate-400',
                    )}>
                      {str(file.action)}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {data.commit_message && (
        <Section title="Commit" icon={<Code2 className="h-3.5 w-3.5" />}>
          <p className="font-mono text-xs text-slate-400">{str(data.commit_message)}</p>
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// QAReview view
// ---------------------------------------------------------------------------

function QAReviewView({ data }: { data: Record<string, unknown> }) {
  const verdict = str(data.verdict ?? '').toLowerCase()
  const vs = VERDICT_STYLE[verdict]
  const comments = arr(data.comments ?? data.issues ?? data.findings)
  const criteria = arr(data.acceptance_criteria ?? data.criteria_results ?? data.checklist)

  return (
    <>
      {/* Verdict banner */}
      {verdict && (
        <div className={clsx(
          'mb-4 flex items-center gap-3 rounded-lg border p-3',
          vs ? `${vs.bg} ${vs.text} border-current/20` : 'border-slate-700 bg-slate-800/40 text-slate-300',
        )}>
          {vs?.icon ?? <Eye className="h-5 w-5" />}
          <div>
            <div className="text-sm font-bold uppercase">{verdict}</div>
            {data.score != null && (
              <div className="text-xs opacity-80">Score: {str(data.score)}</div>
            )}
          </div>
        </div>
      )}

      {/* Review comments */}
      {comments.length > 0 && (
        <Section title={`Comments (${comments.length})`} icon={<ListChecks className="h-3.5 w-3.5" />}>
          <div className="space-y-2">
            {comments.map((c, i) => {
              const comment = obj(c)
              const severity = str(comment.severity ?? '').toLowerCase()
              return (
                <div
                  key={i}
                  className={clsx(
                    'rounded-lg border-l-2 bg-slate-800/40 px-3 py-2',
                    SEVERITY_COLOR[severity] ?? 'border-slate-700 text-slate-400',
                  )}
                >
                  <div className="flex items-center gap-2">
                    {severity && (
                      <span className="text-[10px] font-bold uppercase">{severity}</span>
                    )}
                    {!!comment.file && (
                      <span className="font-mono text-[10px] text-slate-500">{str(comment.file)}</span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-slate-300">
                    {str(comment.message ?? comment.comment ?? comment.description ?? c)}
                  </p>
                  {!!comment.suggestion && (
                    <p className="mt-1 text-[11px] text-slate-500">
                      Fix: {str(comment.suggestion)}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {/* Acceptance criteria checklist */}
      {criteria.length > 0 && (
        <Section title="Acceptance Criteria" icon={<CheckCircle2 className="h-3.5 w-3.5" />}>
          <div className="space-y-1">
            {criteria.map((c, i) => {
              const crit = obj(c)
              const passed = crit.passed === true || crit.status === 'pass' || crit.met === true
              return (
                <div key={i} className="flex items-start gap-2 text-xs">
                  {passed
                    ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                    : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />}
                  <span className={passed ? 'text-slate-400' : 'text-slate-300'}>
                    {str(crit.criteria ?? crit.description ?? crit.name ?? c)}
                  </span>
                </div>
              )
            })}
          </div>
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// View dispatcher
// ---------------------------------------------------------------------------

export const VIEWS: Record<ArtifactKind, React.ComponentType<{ data: Record<string, unknown> }>> = {
  product_spec: ProductSpecView,
  enriched_spec: ProductSpecView, // Same shape, enriched version
  tech_spec: TechSpecView,
  prd_board: PRDBoardView,
  code_artifact: CodeArtifactView,
  qa_review: QAReviewView,
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ArtifactViewer({ kind, data, title, onClose }: ArtifactViewerProps) {
  const [showRaw, setShowRaw] = useState(false)
  const View = VIEWS[kind]

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:p-8"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <div className="flex items-center gap-2">
            <Eye className="h-4 w-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-slate-100">
              {title ?? KIND_TITLES[kind]}
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowRaw((v) => !v)}
              className={clsx(
                'rounded-md px-2 py-1 text-[11px] font-medium transition',
                showRaw
                  ? 'bg-cyan-900/40 text-cyan-400'
                  : 'text-slate-500 hover:text-slate-300',
              )}
            >
              {showRaw ? 'Formatted' : 'JSON'}
            </button>
            <button
              onClick={onClose}
              className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {showRaw ? (
            <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-[#0c0e14] p-3 font-mono text-[11px] leading-relaxed text-slate-300">
              {JSON.stringify(data, null, 2)}
            </pre>
          ) : (
            <View data={data} />
          )}
        </div>
      </div>
    </div>
  )
}
