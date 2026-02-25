import { useState } from 'react'
import {
  Check,
  Eye,
  FileCode,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { VIEWS, KIND_TITLES, type ArtifactKind } from './ArtifactViewer.tsx'
import {
  resolveTicketNodeStatus,
  TICKET_BG,
  TICKET_TEXT,
  TICKET_STATUS_LABEL,
  InfoCell,
} from './PipelineDAG.tsx'
import type { TicketExecution } from '../types/pipeline.ts'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DetailSelection =
  | { type: 'artifact'; kind: ArtifactKind; data: Record<string, unknown>; title?: string }
  | { type: 'ticket'; ticketKey: string; ticket?: TicketExecution; prdTicket?: Record<string, unknown> }

interface DetailPaneProps {
  selection: DetailSelection | null
  onClose: () => void
  className?: string
}

// ---------------------------------------------------------------------------
// Ticket detail view (reuses rendering logic from PipelineDAG TicketDetailPopup)
// ---------------------------------------------------------------------------

function TicketDetailView({
  ticketKey,
  ticket,
  prdTicket,
}: {
  ticketKey: string
  ticket: TicketExecution | undefined
  prdTicket: Record<string, unknown> | undefined
}) {
  const status = ticket ? resolveTicketNodeStatus(ticket) : 'pending'
  const codeArtifact = ticket?.code_artifact as Record<string, unknown> | null
  const qaReview = ticket?.qa_review as Record<string, unknown> | null
  const filesCreated = (codeArtifact?.files_created as string[]) ?? []
  const filesModified = (codeArtifact?.files_modified as string[]) ?? []
  const cost = (codeArtifact?.cost_usd as number) ?? ticket?.attempts ?? 0

  const title = (prdTicket?.title as string) ?? ticketKey
  const description = (prdTicket?.description as string) ?? ''
  const acceptanceCriteria = (prdTicket?.acceptance_criteria as string[]) ?? []
  const agentId = (codeArtifact?.agent_id as string) ?? null

  return (
    <>
      {/* Header */}
      <div className="mb-4">
        <div className="mb-1 flex items-center gap-2">
          <span className="font-mono text-sm font-bold text-cyan-400">{ticketKey}</span>
          <span
            className={clsx(
              'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase',
              TICKET_BG[status],
              TICKET_TEXT[status],
            )}
          >
            {TICKET_STATUS_LABEL[status]}
          </span>
        </div>
        <h3 className="text-base font-semibold text-slate-200">{title}</h3>
      </div>

      {/* Description */}
      {description && (
        <div className="mb-4">
          <div className="mb-1 text-[11px] font-medium uppercase text-slate-500">Description</div>
          <p className="text-sm leading-relaxed text-slate-400">{description}</p>
        </div>
      )}

      {/* Acceptance criteria */}
      {acceptanceCriteria.length > 0 && (
        <div className="mb-4">
          <div className="mb-1 text-[11px] font-medium uppercase text-slate-500">Acceptance Criteria</div>
          <ul className="space-y-1">
            {acceptanceCriteria.map((ac, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-400">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-600" />
                {ac}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Status details */}
      <div className="mb-4 grid grid-cols-2 gap-3">
        <InfoCell label="Status" value={TICKET_STATUS_LABEL[status]} className={TICKET_TEXT[status]} />
        <InfoCell label="Revisions" value={String(Math.max(0, (ticket?.attempts ?? 1) - 1))} />
        {agentId && <InfoCell label="Agent" value={agentId} mono />}
        {typeof cost === 'number' && cost > 0 && (
          <InfoCell label="Cost" value={`$${cost.toFixed(4)}`} mono />
        )}
      </div>

      {/* QA Review */}
      {qaReview && (
        <div className="mb-4">
          <div className="mb-1 text-[11px] font-medium uppercase text-slate-500">QA Review</div>
          <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-3 text-sm">
            {qaReview.verdict != null && (
              <div className="mb-1">
                <span className="text-slate-500">Verdict: </span>
                <span
                  className={clsx(
                    'font-semibold',
                    qaReview.verdict === 'approved' ? 'text-emerald-400' : 'text-amber-400',
                  )}
                >
                  {String(qaReview.verdict)}
                </span>
              </div>
            )}
            {qaReview.code_quality_score != null && (
              <div className="text-slate-400">
                Quality score: {String(qaReview.code_quality_score)}/10
              </div>
            )}
            {Array.isArray(qaReview.revision_instructions) && qaReview.revision_instructions.length > 0 && (
              <div className="mt-2 border-t border-slate-700/40 pt-2">
                <div className="mb-1 text-[10px] uppercase text-slate-500">Revision instructions</div>
                <ul className="space-y-0.5">
                  {(qaReview.revision_instructions as string[]).slice(0, 5).map((instr, i) => (
                    <li key={i} className="text-xs text-slate-400">
                      - {typeof instr === 'string' ? instr : JSON.stringify(instr)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Files */}
      {(filesCreated.length > 0 || filesModified.length > 0) && (
        <div>
          <div className="mb-1 text-[11px] font-medium uppercase text-slate-500">Files</div>
          <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-3">
            {filesCreated.length > 0 && (
              <div className="mb-2">
                <span className="text-[10px] uppercase text-emerald-500">Created</span>
                {filesCreated.map((f) => (
                  <div key={f} className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-400">
                    <FileCode className="h-3 w-3 text-emerald-600" />
                    <span className="font-mono">{f}</span>
                  </div>
                ))}
              </div>
            )}
            {filesModified.length > 0 && (
              <div>
                <span className="text-[10px] uppercase text-amber-500">Modified</span>
                {filesModified.map((f) => (
                  <div key={f} className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-400">
                    <FileCode className="h-3 w-3 text-amber-600" />
                    <span className="font-mono">{f}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function DetailPane({ selection, onClose, className }: DetailPaneProps) {
  const [showRaw, setShowRaw] = useState(false)

  if (!selection) return null

  const isArtifact = selection.type === 'artifact'
  const title = isArtifact
    ? selection.title ?? KIND_TITLES[selection.kind]
    : selection.ticketKey

  return (
    <div
      className={clsx(
        'flex min-h-0 flex-col rounded-xl border border-slate-800 bg-slate-900',
        className,
      )}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <Eye className="h-4 w-4 shrink-0 text-cyan-400" />
          <h3 className="truncate text-sm font-semibold text-slate-100">{title}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {isArtifact && (
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
          )}
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isArtifact ? (
          showRaw ? (
            <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-[#0c0e14] p-3 font-mono text-[11px] leading-relaxed text-slate-300">
              {JSON.stringify(selection.data, null, 2)}
            </pre>
          ) : (
            (() => {
              const View = VIEWS[selection.kind]
              return <View data={selection.data} />
            })()
          )
        ) : (
          <TicketDetailView
            ticketKey={selection.ticketKey}
            ticket={selection.ticket}
            prdTicket={selection.prdTicket}
          />
        )}
      </div>
    </div>
  )
}
