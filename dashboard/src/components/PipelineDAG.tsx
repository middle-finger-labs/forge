import { memo, useCallback, useMemo, useState } from 'react'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import dagre from '@dagrejs/dagre'
import {
  Check,
  Clock,
  Loader2,
  Pause,
  X,
  Code2,
  FileCode,
  GitMerge,
  RefreshCw,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import clsx from 'clsx'
import type { PipelineState, TicketExecution } from '../types/pipeline.ts'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STAGES = [
  'business_analysis',
  'research',
  'architecture',
  'task_decomposition',
  'coding',
  'qa_review',
  'merge',
  'complete',
] as const

type Stage = (typeof STAGES)[number]

const STAGE_LABELS: Record<Stage, string> = {
  business_analysis: 'Business Analysis',
  research: 'Research',
  architecture: 'Architecture',
  task_decomposition: 'Task Decomposition',
  coding: 'Coding',
  qa_review: 'QA Review',
  merge: 'Merge',
  complete: 'Complete',
}

const NODE_W = 200
const NODE_H = 72
const ACTIVE_NODE_W = 224
const ACTIVE_NODE_H = 84
const TICKET_NODE_W = 160
const TICKET_NODE_H = 52
const QA_NODE_W = 56
const QA_NODE_H = 40

// ---------------------------------------------------------------------------
// Stage status (pipeline-level)
// ---------------------------------------------------------------------------

type NodeStatus = 'pending' | 'active' | 'complete' | 'failed' | 'awaiting_approval'

function resolveStageStatus(stage: Stage, state: PipelineState): NodeStatus {
  const current = state.current_stage
  const currentIdx = STAGES.indexOf(current as Stage)
  const stageIdx = STAGES.indexOf(stage)

  if (state.aborted && current === stage) return 'failed'
  if (state.pending_approval && current === stage) return 'awaiting_approval'
  if (current === stage) return 'active'
  if (stageIdx < currentIdx) return 'complete'
  return 'pending'
}

// ---------------------------------------------------------------------------
// Ticket status (6 states with distinct colors)
// ---------------------------------------------------------------------------

type TicketNodeStatus = 'pending' | 'coding' | 'qa_review' | 'revision' | 'merged' | 'failed'

function resolveTicketNodeStatus(ticket: TicketExecution): TicketNodeStatus {
  const s = ticket.status
  if (s === 'completed' || s === 'complete' || s === 'merged') return 'merged'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'in_review') return 'qa_review'
  if (ticket.attempts > 1 && (s === 'running' || s === 'active' || s === 'in_progress')) return 'revision'
  if (s === 'running' || s === 'active' || s === 'in_progress') return 'coding'
  return 'pending'
}

// Stage status visuals (same as before)
const STATUS_ICON: Record<NodeStatus, LucideIcon> = {
  pending: Clock,
  active: Loader2,
  complete: Check,
  failed: X,
  awaiting_approval: Pause,
}
const STATUS_RING: Record<NodeStatus, string> = {
  pending: 'border-slate-700',
  active: 'border-cyan-500 shadow-[0_0_18px_rgba(6,182,212,0.35)]',
  complete: 'border-emerald-600',
  failed: 'border-red-600',
  awaiting_approval: 'border-amber-500 shadow-[0_0_14px_rgba(245,158,11,0.25)]',
}
const STATUS_BG: Record<NodeStatus, string> = {
  pending: 'bg-slate-800/80',
  active: 'bg-slate-800',
  complete: 'bg-emerald-950/60',
  failed: 'bg-red-950/60',
  awaiting_approval: 'bg-amber-950/50',
}
const STATUS_ICON_COLOR: Record<NodeStatus, string> = {
  pending: 'text-slate-500',
  active: 'text-cyan-400 animate-spin',
  complete: 'text-emerald-400',
  failed: 'text-red-400',
  awaiting_approval: 'text-amber-400',
}
const STATUS_TEXT: Record<NodeStatus, string> = {
  pending: 'text-slate-500',
  active: 'text-cyan-300',
  complete: 'text-emerald-300',
  failed: 'text-red-300',
  awaiting_approval: 'text-amber-300',
}

// Ticket status visuals (6-color)
const TICKET_ICON: Record<TicketNodeStatus, LucideIcon> = {
  pending: Clock,
  coding: Loader2,
  qa_review: ShieldCheck,
  revision: RefreshCw,
  merged: GitMerge,
  failed: X,
}
const TICKET_RING: Record<TicketNodeStatus, string> = {
  pending: 'border-slate-700',
  coding: 'border-blue-500 shadow-[0_0_12px_rgba(59,130,246,0.3)]',
  qa_review: 'border-purple-500 shadow-[0_0_12px_rgba(168,85,247,0.3)]',
  revision: 'border-orange-500 shadow-[0_0_12px_rgba(249,115,22,0.3)]',
  merged: 'border-emerald-600',
  failed: 'border-red-600',
}
const TICKET_BG: Record<TicketNodeStatus, string> = {
  pending: 'bg-slate-800/80',
  coding: 'bg-blue-950/50',
  qa_review: 'bg-purple-950/50',
  revision: 'bg-orange-950/50',
  merged: 'bg-emerald-950/60',
  failed: 'bg-red-950/60',
}
const TICKET_ICON_COLOR: Record<TicketNodeStatus, string> = {
  pending: 'text-slate-500',
  coding: 'text-blue-400 animate-spin',
  qa_review: 'text-purple-400 animate-pulse',
  revision: 'text-orange-400 animate-spin',
  merged: 'text-emerald-400',
  failed: 'text-red-400',
}
const TICKET_TEXT: Record<TicketNodeStatus, string> = {
  pending: 'text-slate-500',
  coding: 'text-blue-300',
  qa_review: 'text-purple-300',
  revision: 'text-orange-300',
  merged: 'text-emerald-300',
  failed: 'text-red-300',
}
const TICKET_STATUS_LABEL: Record<TicketNodeStatus, string> = {
  pending: 'pending',
  coding: 'coding',
  qa_review: 'in QA',
  revision: 'revision',
  merged: 'merged',
  failed: 'failed',
}
const TICKET_EDGE_COLOR: Record<TicketNodeStatus, string> = {
  pending: '#334155',
  coding: '#3b82f6',
  qa_review: '#a855f7',
  revision: '#f97316',
  merged: '#059669',
  failed: '#dc2626',
}

// ---------------------------------------------------------------------------
// Custom node data types
// ---------------------------------------------------------------------------

type StageNodeData = {
  label: string
  status: NodeStatus
  isActive: boolean
  cost?: number
  duration?: string
}

type TicketNodeData = {
  label: string
  status: TicketNodeStatus
  ticketKey: string
  attempts: number
  onTicketClick?: (ticketKey: string) => void
}

type GroupNodeData = {
  label: string
  groupIndex: number
}

type QANodeData = {
  label: string
  hasActive: boolean
}

// ---------------------------------------------------------------------------
// Custom stage node
// ---------------------------------------------------------------------------

const StageNode = memo(function StageNode({
  data,
}: NodeProps<Node<StageNodeData>>) {
  const Icon = STATUS_ICON[data.status]
  return (
    <div
      className={clsx(
        'rounded-xl border-2 px-4 py-3 transition-all',
        STATUS_RING[data.status],
        STATUS_BG[data.status],
        data.isActive && 'scale-105',
      )}
      style={{
        width: data.isActive ? ACTIVE_NODE_W : NODE_W,
        minHeight: data.isActive ? ACTIVE_NODE_H : NODE_H,
      }}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-600 !border-slate-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} className="!bg-slate-600 !border-slate-500 !w-2 !h-2" />
      <div className="flex items-center gap-2.5">
        <div className={clsx('shrink-0', STATUS_ICON_COLOR[data.status])}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className={clsx(
            'truncate text-sm font-semibold',
            data.isActive ? 'text-slate-100' : STATUS_TEXT[data.status],
          )}>
            {data.label}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-slate-500">
            {data.duration && <span>{data.duration}</span>}
            {data.cost != null && <span>${data.cost.toFixed(4)}</span>}
          </div>
        </div>
      </div>
    </div>
  )
})

// ---------------------------------------------------------------------------
// Custom ticket node (with 6-color status and click)
// ---------------------------------------------------------------------------

const TicketNode = memo(function TicketNode({
  data,
}: NodeProps<Node<TicketNodeData>>) {
  const Icon = TICKET_ICON[data.status]
  const isActive = data.status === 'coding' || data.status === 'qa_review' || data.status === 'revision'

  return (
    <div
      className={clsx(
        'rounded-lg border px-3 py-2 transition-all cursor-pointer hover:brightness-125',
        TICKET_RING[data.status],
        TICKET_BG[data.status],
      )}
      style={{ width: TICKET_NODE_W, minHeight: TICKET_NODE_H }}
      onClick={(e) => {
        e.stopPropagation()
        data.onTicketClick?.(data.ticketKey)
      }}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-600 !border-slate-500 !w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Right} className="!bg-slate-600 !border-slate-500 !w-1.5 !h-1.5" />
      {/* Top handle for QA loopback */}
      <Handle type="target" position={Position.Top} id="qa-return" className="!bg-purple-600 !border-purple-500 !w-1.5 !h-1.5" />

      <div className="flex items-center gap-2">
        <div className={clsx('shrink-0', TICKET_ICON_COLOR[data.status])}>
          <Icon className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className={clsx('truncate font-mono text-xs font-medium', TICKET_TEXT[data.status])}>
            {data.ticketKey}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[10px]">
            <span className={TICKET_TEXT[data.status]}>
              {TICKET_STATUS_LABEL[data.status]}
            </span>
            {data.attempts > 1 && (
              <span className="text-slate-500">rev {data.attempts - 1}</span>
            )}
            {isActive && (
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
            )}
          </div>
        </div>
      </div>
    </div>
  )
})

// ---------------------------------------------------------------------------
// Group swim lane container
// ---------------------------------------------------------------------------

const GroupSwimlane = memo(function GroupSwimlane({
  data,
}: NodeProps<Node<GroupNodeData>>) {
  return (
    <div className="rounded-2xl border border-dashed border-cyan-800/40 bg-cyan-950/8 p-2">
      <Handle type="target" position={Position.Left} className="!bg-cyan-700 !border-cyan-600 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} className="!bg-cyan-700 !border-cyan-600 !w-2 !h-2" />
      <div className="mb-1 flex items-center gap-1.5 px-2 pt-1 text-[10px] font-medium uppercase tracking-wider text-cyan-600">
        <Code2 className="h-3 w-3" />
        {data.label}
      </div>
    </div>
  )
})

// ---------------------------------------------------------------------------
// QA node (small node within each group for review cycle)
// ---------------------------------------------------------------------------

const QAReviewNode = memo(function QAReviewNode({
  data,
}: NodeProps<Node<QANodeData>>) {
  return (
    <div
      className={clsx(
        'flex items-center justify-center rounded-lg border px-2 py-1',
        data.hasActive
          ? 'border-purple-600 bg-purple-950/40 shadow-[0_0_10px_rgba(168,85,247,0.2)]'
          : 'border-slate-700 bg-slate-800/60',
      )}
      style={{ width: QA_NODE_W, height: QA_NODE_H }}
    >
      <Handle type="target" position={Position.Left} className="!bg-purple-600 !border-purple-500 !w-1.5 !h-1.5" />
      {/* Bottom handle for loopback to tickets */}
      <Handle type="source" position={Position.Bottom} id="qa-loop" className="!bg-orange-500 !border-orange-400 !w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Right} className="!bg-slate-600 !border-slate-500 !w-1.5 !h-1.5" />
      <div className={clsx(
        'text-[10px] font-bold uppercase',
        data.hasActive ? 'text-purple-400' : 'text-slate-500',
      )}>
        {data.label}
      </div>
    </div>
  )
})

// ---------------------------------------------------------------------------
// Ticket detail popup
// ---------------------------------------------------------------------------

interface TicketDetailProps {
  ticketKey: string
  ticket: TicketExecution | undefined
  prdTicket: Record<string, unknown> | undefined
  onClose: () => void
}

function TicketDetailPopup({ ticketKey, ticket, prdTicket, onClose }: TicketDetailProps) {
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button onClick={onClose} className="absolute right-4 top-4 text-slate-500 hover:text-slate-300">
          <X className="h-5 w-5" />
        </button>

        {/* Header */}
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-sm font-bold text-cyan-400">{ticketKey}</span>
            <span className={clsx(
              'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase',
              TICKET_BG[status],
              TICKET_TEXT[status],
            )}>
              {TICKET_STATUS_LABEL[status]}
            </span>
          </div>
          <h3 className="text-base font-semibold text-slate-200">{title}</h3>
        </div>

        {/* Description */}
        {description && (
          <div className="mb-4">
            <div className="text-[11px] font-medium uppercase text-slate-500 mb-1">Description</div>
            <p className="text-sm text-slate-400 leading-relaxed">{description}</p>
          </div>
        )}

        {/* Acceptance criteria */}
        {acceptanceCriteria.length > 0 && (
          <div className="mb-4">
            <div className="text-[11px] font-medium uppercase text-slate-500 mb-1">Acceptance Criteria</div>
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
            <div className="text-[11px] font-medium uppercase text-slate-500 mb-1">QA Review</div>
            <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-3 text-sm">
              {qaReview.verdict != null && (
                <div className="mb-1">
                  <span className="text-slate-500">Verdict: </span>
                  <span className={clsx(
                    'font-semibold',
                    qaReview.verdict === 'approved' ? 'text-emerald-400' : 'text-amber-400',
                  )}>
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
                  <div className="text-[10px] uppercase text-slate-500 mb-1">Revision instructions</div>
                  <ul className="space-y-0.5">
                    {(qaReview.revision_instructions as string[]).slice(0, 5).map((instr, i) => (
                      <li key={i} className="text-xs text-slate-400">- {typeof instr === 'string' ? instr : JSON.stringify(instr)}</li>
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
            <div className="text-[11px] font-medium uppercase text-slate-500 mb-1">Files</div>
            <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-3">
              {filesCreated.length > 0 && (
                <div className="mb-2">
                  <span className="text-[10px] uppercase text-emerald-500">Created</span>
                  {filesCreated.map((f) => (
                    <div key={f} className="flex items-center gap-1.5 text-xs text-slate-400 mt-0.5">
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
                    <div key={f} className="flex items-center gap-1.5 text-xs text-slate-400 mt-0.5">
                      <FileCode className="h-3 w-3 text-amber-600" />
                      <span className="font-mono">{f}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function InfoCell({ label, value, className, mono }: {
  label: string; value: string; className?: string; mono?: boolean
}) {
  return (
    <div className="rounded-lg border border-slate-700/40 bg-slate-800/30 px-3 py-2">
      <div className="text-[10px] uppercase text-slate-600">{label}</div>
      <div className={clsx('text-sm font-medium', className ?? 'text-slate-300', mono && 'font-mono')}>
        {value}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Node type registry
// ---------------------------------------------------------------------------

const nodeTypes = {
  stage: StageNode,
  ticket: TicketNode,
  groupSwimlane: GroupSwimlane,
  qaReview: QAReviewNode,
}

// ---------------------------------------------------------------------------
// Dagre layout
// ---------------------------------------------------------------------------

function layoutGraph(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph({ compound: true })
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({
    rankdir: 'LR',
    nodesep: 24,
    ranksep: 70,
    marginx: 40,
    marginy: 40,
  })

  // Only add top-level nodes to dagre — child nodes (tickets, QA inside
  // swim-lane groups) already carry relative positions and compound graph
  // layout in dagre v2 can leave children without rank assignments, causing
  // "can't access property 'rank'" crashes in removeEmptyRanks.
  const childNodeIds = new Set<string>()
  for (const node of nodes) {
    if (node.parentId) {
      childNodeIds.add(node.id)
      continue
    }
    let w: number, h: number
    if (node.type === 'groupSwimlane') {
      w = node.style?.width as number ?? 260
      h = node.style?.height as number ?? 180
    } else {
      w = node.data?.isActive ? ACTIVE_NODE_W : NODE_W
      h = node.data?.isActive ? ACTIVE_NODE_H : NODE_H
    }
    g.setNode(node.id, { width: w, height: h })
  }

  for (const edge of edges) {
    // Skip edges that involve child nodes — dagre doesn't know about them
    if (childNodeIds.has(edge.source) || childNodeIds.has(edge.target)) continue
    g.setEdge(edge.source, edge.target)
  }

  dagre.layout(g)

  const positioned = nodes.map((node) => {
    // Child nodes keep their relative positions (set in buildGraph)
    if (node.parentId) return node
    const pos = g.node(node.id)
    if (!pos) return node
    return {
      ...node,
      position: {
        x: pos.x - (pos.width ?? 0) / 2,
        y: pos.y - (pos.height ?? 0) / 2,
      },
    }
  })

  return { nodes: positioned, edges }
}

// ---------------------------------------------------------------------------
// Build graph from pipeline state
// ---------------------------------------------------------------------------

function buildGraph(
  state: PipelineState,
  tickets: TicketExecution[],
  onTicketClick?: (ticketKey: string) => void,
  _onStageClick?: (stage: string) => void,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = []
  const edges: Edge[] = []

  // Determine if we should expand coding sub-graph
  const codingIdx = STAGES.indexOf('coding')
  const currentIdx = STAGES.indexOf(state.current_stage as Stage)
  const prdBoard = state.prd_board as Record<string, unknown> | null
  const executionOrder = (prdBoard?.execution_order as string[][]) ?? []
  const prdTickets = (prdBoard?.tickets as Record<string, unknown>[]) ?? []

  const shouldExpand =
    currentIdx >= codingIdx &&
    state.current_stage !== 'complete' &&
    (tickets.length > 0 || executionOrder.length > 0)

  // Stages to skip when expanded (handled by swim lanes)
  const expandedSkip = new Set<Stage>(['coding', 'qa_review', 'merge'])

  // --- Stage nodes ---
  for (const stage of STAGES) {
    if (shouldExpand && expandedSkip.has(stage)) continue

    const status = resolveStageStatus(stage, state)
    const isActive = status === 'active'

    nodes.push({
      id: stage,
      type: 'stage',
      position: { x: 0, y: 0 },
      data: {
        label: STAGE_LABELS[stage],
        status,
        isActive,
      } satisfies StageNodeData,
    })
  }

  // --- Stage edges (for non-expanded stages) ---
  const stageSequence = shouldExpand
    ? STAGES.filter((s) => !expandedSkip.has(s))
    : [...STAGES]

  for (let i = 0; i < stageSequence.length - 1; i++) {
    const src = stageSequence[i]
    const tgt = stageSequence[i + 1]
    const srcStatus = resolveStageStatus(src, state)
    const tgtStatus = resolveStageStatus(tgt, state)
    const isActiveEdge = srcStatus === 'active' || tgtStatus === 'active'
    const isCompleteEdge = srcStatus === 'complete' && tgtStatus === 'complete'

    edges.push({
      id: `${src}->${tgt}`,
      source: src,
      target: tgt,
      type: 'default',
      animated: isActiveEdge,
      style: {
        stroke: isActiveEdge ? '#06b6d4' : isCompleteEdge ? '#059669' : '#334155',
        strokeWidth: isActiveEdge ? 2.5 : 1.5,
        opacity: srcStatus === 'pending' && tgtStatus === 'pending' ? 0.4 : 1,
      },
    })
  }

  // --- Expanded coding sub-graph ---
  if (shouldExpand) {
    // Map tickets by key
    const ticketsByKey = new Map<string, TicketExecution>()
    for (const t of tickets) ticketsByKey.set(t.ticket_key, t)

    const prdTicketsByKey = new Map<string, Record<string, unknown>>()
    for (const t of prdTickets) {
      const key = t.ticket_key as string
      if (key) prdTicketsByKey.set(key, t)
    }

    // Use execution_order for groups, or fall back to single group
    const groups: string[][] = executionOrder.length > 0
      ? executionOrder
      : [tickets.map((t) => t.ticket_key)]

    for (let gIdx = 0; gIdx < groups.length; gIdx++) {
      const group = groups[gIdx]
      const groupId = `group-${gIdx}`
      const qaNodeId = `qa-${gIdx}`

      // Resolve statuses for all tickets in group
      const ticketStatuses = group.map((tk) => {
        const exec = ticketsByKey.get(tk)
        return exec ? resolveTicketNodeStatus(exec) : 'pending' as TicketNodeStatus
      })
      const hasActiveQA = ticketStatuses.some((s) => s === 'qa_review' || s === 'revision')
      const hasAnyActive = ticketStatuses.some((s) => s === 'coding' || s === 'qa_review' || s === 'revision')

      // Group swim lane
      const groupH = Math.max(120, group.length * (TICKET_NODE_H + 14) + 60)
      const groupW = TICKET_NODE_W + QA_NODE_W + 80

      nodes.push({
        id: groupId,
        type: 'groupSwimlane',
        position: { x: 0, y: 0 },
        data: {
          label: `Group ${gIdx}`,
          groupIndex: gIdx,
        } satisfies GroupNodeData,
        style: { width: groupW, height: groupH },
      })

      // QA node inside the group
      const qaY = Math.max(40, (groupH - QA_NODE_H) / 2)
      nodes.push({
        id: qaNodeId,
        type: 'qaReview',
        position: { x: TICKET_NODE_W + 40, y: qaY },
        parentId: groupId,
        extent: 'parent' as const,
        data: {
          label: 'QA',
          hasActive: hasActiveQA,
        } satisfies QANodeData,
      })

      // Ticket nodes inside the group
      for (let tIdx = 0; tIdx < group.length; tIdx++) {
        const tk = group[tIdx]
        const exec = ticketsByKey.get(tk)
        const status = ticketStatuses[tIdx]
        const ticketNodeId = `ticket-${tk}`

        nodes.push({
          id: ticketNodeId,
          type: 'ticket',
          position: { x: 16, y: 44 + tIdx * (TICKET_NODE_H + 14) },
          parentId: groupId,
          extent: 'parent' as const,
          data: {
            label: tk,
            status,
            ticketKey: tk,
            attempts: exec?.attempts ?? 0,
            onTicketClick,
          } satisfies TicketNodeData,
        })

        // Edge: ticket → QA (forward: coding → QA)
        const isQAActive = status === 'qa_review' || status === 'coding'
        edges.push({
          id: `${ticketNodeId}->${qaNodeId}`,
          source: ticketNodeId,
          target: qaNodeId,
          type: 'default',
          animated: isQAActive,
          style: {
            stroke: TICKET_EDGE_COLOR[status],
            strokeWidth: isQAActive ? 2 : 1,
            opacity: status === 'pending' ? 0.3 : 0.8,
          },
        })

        // Edge: QA → ticket loopback (revision cycle)
        if (status === 'revision') {
          edges.push({
            id: `${qaNodeId}->${ticketNodeId}-loop`,
            source: qaNodeId,
            sourceHandle: 'qa-loop',
            target: ticketNodeId,
            targetHandle: 'qa-return',
            type: 'default',
            animated: true,
            style: {
              stroke: '#f97316',
              strokeWidth: 2,
              strokeDasharray: '6 3',
            },
          })
        }
      }

      // Edge: task_decomposition → first group
      if (gIdx === 0) {
        edges.push({
          id: `task_decomposition->${groupId}`,
          source: 'task_decomposition',
          target: groupId,
          type: 'default',
          animated: hasAnyActive,
          style: {
            stroke: hasAnyActive ? '#06b6d4' : '#334155',
            strokeWidth: hasAnyActive ? 2 : 1.5,
          },
        })
      }

      // Edge: previous group → this group (dependency arrow)
      if (gIdx > 0) {
        const prevGroupId = `group-${gIdx - 1}`
        const prevGroupDone = groups[gIdx - 1].every((tk) => {
          const exec = ticketsByKey.get(tk)
          if (!exec) return false
          const s = resolveTicketNodeStatus(exec)
          return s === 'merged' || s === 'failed'
        })

        edges.push({
          id: `${prevGroupId}->${groupId}`,
          source: prevGroupId,
          target: groupId,
          type: 'default',
          animated: !prevGroupDone && hasAnyActive,
          style: {
            stroke: prevGroupDone ? '#059669' : hasAnyActive ? '#06b6d4' : '#334155',
            strokeWidth: 2,
          },
        })
      }

      // Edge: last group → complete
      if (gIdx === groups.length - 1) {
        edges.push({
          id: `${groupId}->complete`,
          source: groupId,
          target: 'complete',
          type: 'default',
          animated: false,
          style: {
            stroke: '#334155',
            strokeWidth: 1.5,
          },
        })
      }
    }

    // Remove the direct task_decomposition → complete edge if present
    const removeIds = new Set(['task_decomposition->complete'])
    const filtered = edges.filter((e) => !removeIds.has(e.id))
    edges.length = 0
    edges.push(...filtered)
  }

  return layoutGraph(nodes, edges)
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PipelineDAGProps {
  state: PipelineState
  tickets?: TicketExecution[]
  onStageClick?: (stage: string) => void
  onTicketClick?: (ticketKey: string) => void
  className?: string
}

export default function PipelineDAG({
  state,
  tickets = [],
  onStageClick,
  onTicketClick,
  className,
}: PipelineDAGProps) {
  const [popupTicket, setPopupTicket] = useState<string | null>(null)

  const handleTicketClick = useCallback(
    (ticketKey: string) => {
      setPopupTicket(ticketKey)
      onTicketClick?.(ticketKey)
    },
    [onTicketClick],
  )

  const { nodes, edges } = useMemo(
    () => buildGraph(state, tickets, handleTicketClick, onStageClick),
    [state, tickets, handleTicketClick, onStageClick],
  )

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.type === 'stage' && onStageClick) {
        onStageClick(node.id)
      }
    },
    [onStageClick],
  )

  // Lookup data for popup
  const prdBoard = state.prd_board as Record<string, unknown> | null
  const prdTickets = (prdBoard?.tickets as Record<string, unknown>[]) ?? []
  const popupExec = popupTicket ? tickets.find((t) => t.ticket_key === popupTicket) : undefined
  const popupPrd = popupTicket ? prdTickets.find((t) => (t.ticket_key as string) === popupTicket) : undefined

  return (
    <>
      <div className={clsx('h-[340px] w-full rounded-xl border border-slate-800 bg-slate-950', className)}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={handleNodeClick}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          panOnDrag
          zoomOnScroll={false}
          panOnScroll
          preventScrolling={false}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1e293b" />
        </ReactFlow>
      </div>

      {/* Ticket detail popup */}
      {popupTicket && (
        <TicketDetailPopup
          ticketKey={popupTicket}
          ticket={popupExec}
          prdTicket={popupPrd}
          onClose={() => setPopupTicket(null)}
        />
      )}
    </>
  )
}
