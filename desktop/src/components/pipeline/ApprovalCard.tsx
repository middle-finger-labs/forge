import { useState, useCallback } from "react";
import {
  Zap,
  ChevronDown,
  ChevronRight,
  Check,
  X,
  MessageSquare,
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────

export interface ApprovalDecision {
  userId: string;
  userName: string;
  approved: boolean;
  comment?: string;
  timestamp: string;
}

interface ApprovalCardProps {
  stage: string;
  summary: string;
  approvalId: string;
  /** Expandable content sections */
  sections?: ApprovalSection[];
  /** Existing decisions (for multi-reviewer view) */
  decisions?: ApprovalDecision[];
  /** Whether this approval is still pending */
  pending?: boolean;
  /** Called when user approves */
  onApprove?: (comment?: string) => void;
  /** Called when user requests changes */
  onRequestChanges?: (comment: string) => void;
}

interface ApprovalSection {
  title: string;
  content: string;
  /** Markdown or plain text */
  format?: "markdown" | "text";
}

// ─── ApprovalCard ────────────────────────────────────

export function ApprovalCard({
  stage,
  summary,
  sections = [],
  decisions = [],
  pending = true,
  onApprove,
  onRequestChanges,
}: ApprovalCardProps) {
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<number>>(
    new Set()
  );

  const toggleSection = useCallback((idx: number) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  const handleApprove = useCallback(() => {
    onApprove?.(comment.trim() || undefined);
  }, [onApprove, comment]);

  const handleReject = useCallback(() => {
    if (!comment.trim()) {
      setShowComment(true);
      return;
    }
    onRequestChanges?.(comment.trim());
  }, [onRequestChanges, comment]);

  const hasDecisions = decisions.length > 0;
  const approvedCount = decisions.filter((d) => d.approved).length;
  const rejectedCount = decisions.filter((d) => !d.approved).length;

  return (
    <div
      className={cn(
        "rounded-lg border max-w-lg overflow-hidden",
        pending
          ? "border-[var(--forge-warning)]/40 bg-[var(--forge-warning)]/5"
          : hasDecisions && rejectedCount > 0
            ? "border-[var(--forge-error)]/30 bg-[var(--forge-error)]/5"
            : "border-[var(--forge-success)]/30 bg-[var(--forge-success)]/5"
      )}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--forge-border)]/30">
        <div className="flex items-center gap-2 mb-1.5">
          <Zap
            className={cn(
              "w-4 h-4",
              pending
                ? "text-[var(--forge-warning)]"
                : "text-[var(--forge-success)]"
            )}
          />
          <span
            className={cn(
              "text-sm font-semibold",
              pending
                ? "text-[var(--forge-warning)]"
                : "text-[var(--forge-success)]"
            )}
          >
            {pending ? "Approval Required" : "Approved"}
          </span>
          <span className="text-xs text-[var(--forge-text-muted)] ml-auto">
            {stage}
          </span>
        </div>
        <p className="text-sm text-[var(--forge-text)] leading-relaxed">
          {summary}
        </p>
      </div>

      {/* Expandable sections */}
      {sections.length > 0 && (
        <div className="border-b border-[var(--forge-border)]/30">
          {sections.map((section, i) => (
            <div key={i}>
              <button
                onClick={() => toggleSection(i)}
                className="w-full flex items-center gap-2 px-4 py-2 text-xs font-medium text-[var(--forge-text-muted)] hover:text-white hover:bg-white/[0.02] transition-colors text-left"
              >
                {expandedSections.has(i) ? (
                  <ChevronDown className="w-3 h-3 shrink-0" />
                ) : (
                  <ChevronRight className="w-3 h-3 shrink-0" />
                )}
                {section.title}
              </button>
              {expandedSections.has(i) && (
                <div className="px-4 pb-3">
                  <pre className="text-xs text-[var(--forge-text)] bg-[var(--forge-bg)] rounded-lg p-3 overflow-x-auto whitespace-pre-wrap font-mono leading-5 max-h-48 overflow-y-auto">
                    {section.content}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Existing decisions */}
      {hasDecisions && (
        <div className="px-4 py-2.5 border-b border-[var(--forge-border)]/30">
          <div className="flex items-center gap-2 mb-2">
            <User className="w-3 h-3 text-[var(--forge-text-muted)]" />
            <span className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
              Reviews ({approvedCount} approved
              {rejectedCount > 0 ? `, ${rejectedCount} changes requested` : ""})
            </span>
          </div>
          <div className="space-y-1.5">
            {decisions.map((d, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span
                  className={cn(
                    "shrink-0 mt-0.5",
                    d.approved
                      ? "text-[var(--forge-success)]"
                      : "text-[var(--forge-error)]"
                  )}
                >
                  {d.approved ? (
                    <Check className="w-3 h-3" />
                  ) : (
                    <X className="w-3 h-3" />
                  )}
                </span>
                <div className="min-w-0">
                  <span className="font-medium text-white">
                    {d.userName}
                  </span>
                  <span className="text-[var(--forge-text-muted)]">
                    {" "}
                    {d.approved ? "approved" : "requested changes"}
                  </span>
                  {d.comment && (
                    <p className="text-[var(--forge-text-muted)] mt-0.5 italic">
                      "{d.comment}"
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions — only for pending approvals */}
      {pending && (
        <div className="px-4 py-3">
          {/* Comment field */}
          {showComment && (
            <div className="mb-3">
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Add a comment..."
                className={cn(
                  "w-full px-3 py-2 text-xs rounded-lg resize-none",
                  "bg-[var(--forge-bg)] border border-[var(--forge-border)]",
                  "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]",
                  "outline-none focus:border-[var(--forge-accent)] transition-colors"
                )}
                rows={3}
              />
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={handleApprove}
              className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md bg-[var(--forge-success)] text-white hover:opacity-90 transition-opacity"
            >
              <Check className="w-3 h-3" />
              Approve
            </button>
            <button
              onClick={handleReject}
              className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md bg-[var(--forge-error)] text-white hover:opacity-90 transition-opacity"
            >
              <X className="w-3 h-3" />
              Request Changes
            </button>
            {!showComment && (
              <button
                onClick={() => setShowComment(true)}
                className="flex items-center gap-1 text-xs text-[var(--forge-text-muted)] hover:text-white transition-colors ml-1"
              >
                <MessageSquare className="w-3 h-3" />
                Comment
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
