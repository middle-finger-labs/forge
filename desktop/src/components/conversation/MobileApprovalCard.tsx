import { useState, useCallback } from "react";
import {
  Zap,
  ChevronDown,
  ChevronRight,
  Check,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ApprovalDecision } from "@/components/pipeline/ApprovalCard";

// ─── Haptic feedback helper ─────────────────────────

async function hapticFeedback(style: "light" | "medium" | "heavy" = "medium") {
  try {
    const haptics = await import("@tauri-apps/plugin-haptics");
    await haptics.impactFeedback(style as never);
  } catch {
    // Not available on desktop — silently ignore
  }
}

// ─── Props ──────────────────────────────────────────

interface MobileApprovalCardProps {
  stage: string;
  summary: string;
  approvalId: string;
  sections?: Array<{ title: string; content: string }>;
  decisions?: ApprovalDecision[];
  pending?: boolean;
  onApprove?: (comment?: string) => void;
  onRequestChanges?: (comment: string) => void;
}

// ─── Component ──────────────────────────────────────

export function MobileApprovalCard({
  stage,
  summary,
  sections = [],
  decisions = [],
  pending = true,
  onApprove,
  onRequestChanges,
}: MobileApprovalCardProps) {
  const [showCommentModal, setShowCommentModal] = useState(false);
  const [comment, setComment] = useState("");
  const [decided, setDecided] = useState<"approved" | "rejected" | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<number>>(new Set());

  const isPending = pending && !decided;

  const toggleSection = useCallback((idx: number) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  const handleApprove = useCallback(async () => {
    await hapticFeedback("medium");
    setDecided("approved");
    onApprove?.();
  }, [onApprove]);

  const handleRequestChanges = useCallback(() => {
    setShowCommentModal(true);
  }, []);

  const submitChangesRequest = useCallback(async () => {
    if (!comment.trim()) return;
    await hapticFeedback("heavy");
    setDecided("rejected");
    setShowCommentModal(false);
    onRequestChanges?.(comment.trim());
  }, [comment, onRequestChanges]);

  // Compact decided state
  if (decided) {
    return (
      <div
        className={cn(
          "flex items-center gap-3 px-4 py-3 rounded-xl",
          decided === "approved"
            ? "bg-[var(--forge-success)]/10 border border-[var(--forge-success)]/20"
            : "bg-[var(--forge-error)]/10 border border-[var(--forge-error)]/20"
        )}
      >
        <span className="text-lg">{decided === "approved" ? "\u2705" : "\u274C"}</span>
        <div className="min-w-0 flex-1">
          <span className={cn(
            "text-sm font-medium",
            decided === "approved" ? "text-[var(--forge-success)]" : "text-[var(--forge-error)]"
          )}>
            {decided === "approved" ? "Approved" : "Changes Requested"} by You
          </span>
          <p className="text-xs text-[var(--forge-text-muted)] truncate mt-0.5">{stage}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className={cn(
          "rounded-xl border overflow-hidden w-full",
          isPending
            ? "border-[var(--forge-warning)]/40 bg-[var(--forge-warning)]/5"
            : "border-[var(--forge-success)]/30 bg-[var(--forge-success)]/5"
        )}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-[var(--forge-border)]/30">
          <div className="flex items-center gap-2 mb-1.5">
            <Zap className="w-4 h-4 text-[var(--forge-warning)]" />
            <span className="text-sm font-semibold text-[var(--forge-warning)]">
              Approval Required
            </span>
            <span className="text-xs text-[var(--forge-text-muted)] ml-auto shrink-0">
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
                  className="w-full flex items-center gap-2 px-4 py-3 text-xs font-medium text-[var(--forge-text-muted)] active:bg-white/[0.03] text-left"
                >
                  {expandedSections.has(i) ? (
                    <ChevronDown className="w-3.5 h-3.5 shrink-0" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 shrink-0" />
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
        {decisions.length > 0 && (
          <div className="px-4 py-3 border-b border-[var(--forge-border)]/30">
            {decisions.map((d, i) => (
              <div key={i} className="flex items-start gap-2 text-xs mb-1 last:mb-0">
                <span className={d.approved ? "text-[var(--forge-success)]" : "text-[var(--forge-error)]"}>
                  {d.approved ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                </span>
                <span className="text-[var(--forge-text)]">
                  <strong className="text-white">{d.userName}</strong>{" "}
                  {d.approved ? "approved" : "requested changes"}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Action buttons — large touch targets (min 44pt) */}
        {isPending && (
          <div className="px-4 py-4 flex gap-3">
            <button
              onClick={handleApprove}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-[var(--forge-success)] text-white font-medium text-sm active:opacity-80 transition-opacity min-h-[44px]"
            >
              <Check className="w-5 h-5" />
              Approve
            </button>
            <button
              onClick={handleRequestChanges}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-[var(--forge-error)] text-white font-medium text-sm active:opacity-80 transition-opacity min-h-[44px]"
            >
              <X className="w-5 h-5" />
              Request Changes
            </button>
          </div>
        )}
      </div>

      {/* Comment modal */}
      {showCommentModal && (
        <CommentModal
          onSubmit={submitChangesRequest}
          onClose={() => setShowCommentModal(false)}
          comment={comment}
          setComment={setComment}
        />
      )}
    </>
  );
}

// ─── Comment Modal ──────────────────────────────────

function CommentModal({
  onSubmit,
  onClose,
  comment,
  setComment,
}: {
  onSubmit: () => void;
  onClose: () => void;
  comment: string;
  setComment: (v: string) => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose} />
      <div className="fixed inset-x-4 top-1/3 z-50 rounded-2xl bg-[var(--forge-bg)] border border-[var(--forge-border)] shadow-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--forge-border)]">
          <h3 className="text-sm font-semibold text-white">Request Changes</h3>
          <p className="text-xs text-[var(--forge-text-muted)] mt-0.5">
            Describe what needs to be changed
          </p>
        </div>

        <div className="p-4">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Describe the changes needed..."
            autoFocus
            className={cn(
              "w-full px-3 py-3 text-sm rounded-xl resize-none",
              "bg-[var(--forge-sidebar)] border border-[var(--forge-border)]",
              "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]",
              "outline-none focus:border-[var(--forge-accent)] transition-colors"
            )}
            rows={4}
          />
        </div>

        <div className="flex gap-3 px-4 pb-4">
          <button
            onClick={onClose}
            className="flex-1 py-3 rounded-xl border border-[var(--forge-border)] text-[var(--forge-text)] text-sm font-medium active:bg-[var(--forge-hover)] min-h-[44px]"
          >
            Cancel
          </button>
          <button
            onClick={onSubmit}
            disabled={!comment.trim()}
            className={cn(
              "flex-1 py-3 rounded-xl text-white text-sm font-medium min-h-[44px]",
              comment.trim()
                ? "bg-[var(--forge-error)] active:opacity-80"
                : "bg-[var(--forge-error)]/40 cursor-not-allowed"
            )}
          >
            Submit
          </button>
        </div>
      </div>
    </>
  );
}
