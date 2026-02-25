import { useState, useRef, useEffect, useCallback } from "react";
import { X, Zap, GitBranch, DollarSign, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Props ───────────────────────────────────────────

interface NewPipelineModalProps {
  onClose: () => void;
  onCreate: (spec: string, options: PipelineOptions) => void;
}

export interface PipelineOptions {
  repo?: string;
  branch?: string;
  budgetLimit?: number;
}

// ─── NewPipelineModal ────────────────────────────────

export function NewPipelineModal({ onClose, onCreate }: NewPipelineModalProps) {
  const [spec, setSpec] = useState("");
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("");
  const [budgetStr, setBudgetStr] = useState("");
  const [showOptions, setShowOptions] = useState(false);
  const [creating, setCreating] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Focus textarea on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Escape to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleCreate = useCallback(async () => {
    if (!spec.trim() || creating) return;
    setCreating(true);

    const options: PipelineOptions = {};
    if (repo.trim()) options.repo = repo.trim();
    if (branch.trim()) options.branch = branch.trim();
    const budget = parseFloat(budgetStr);
    if (!isNaN(budget) && budget > 0) options.budgetLimit = budget;

    onCreate(spec.trim(), options);
  }, [spec, repo, branch, budgetStr, creating, onCreate]);

  // Cmd+Enter to create
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        handleCreate();
      }
    },
    [handleCreate]
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-2xl mx-4 bg-[var(--forge-bg)] border border-[var(--forge-border)] rounded-xl shadow-2xl flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--forge-border)] shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[var(--forge-accent)]/10 flex items-center justify-center">
              <Zap className="w-4 h-4 text-[var(--forge-accent)]" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                New Pipeline
              </h2>
              <p className="text-xs text-[var(--forge-text-muted)]">
                Your agent team will collaborate to build it
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {/* Spec textarea */}
          <div>
            <label className="block text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
              What do you want to build?
            </label>
            <textarea
              ref={textareaRef}
              value={spec}
              onChange={(e) => setSpec(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Describe what you want to build... e.g., 'Build an invoice management system with PDF generation, email notifications, and Stripe integration for recurring billing'"
              className={cn(
                "w-full min-h-[160px] px-4 py-3 rounded-lg",
                "bg-[var(--forge-channel)] border border-[var(--forge-border)]",
                "text-sm text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                "resize-none outline-none",
                "focus:border-[var(--forge-accent)] transition-colors"
              )}
            />
            <p className="text-[10px] text-[var(--forge-text-muted)] mt-1.5">
              Be as detailed as possible. The BA will refine requirements, but a
              good spec leads to better results.
            </p>
          </div>

          {/* Toggle optional fields */}
          <button
            onClick={() => setShowOptions(!showOptions)}
            className="text-xs text-[var(--forge-accent)] hover:text-[var(--forge-accent)]/80 transition-colors"
          >
            {showOptions ? "Hide" : "Show"} advanced options
          </button>

          {/* Optional fields */}
          {showOptions && (
            <div className="space-y-3 animate-in">
              {/* Repo */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-[var(--forge-text-muted)] mb-1.5">
                  <GitBranch className="w-3 h-3" />
                  Target Repository
                </label>
                <input
                  value={repo}
                  onChange={(e) => setRepo(e.target.value)}
                  placeholder="org/repo-name"
                  className={cn(
                    "w-full px-3 py-2 rounded-lg text-sm",
                    "bg-[var(--forge-channel)] border border-[var(--forge-border)]",
                    "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                    "outline-none focus:border-[var(--forge-accent)] transition-colors"
                  )}
                />
              </div>

              {/* Branch */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-[var(--forge-text-muted)] mb-1.5">
                  <GitBranch className="w-3 h-3" />
                  Branch Name
                </label>
                <input
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  placeholder="feature/my-feature"
                  className={cn(
                    "w-full px-3 py-2 rounded-lg text-sm",
                    "bg-[var(--forge-channel)] border border-[var(--forge-border)]",
                    "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                    "outline-none focus:border-[var(--forge-accent)] transition-colors"
                  )}
                />
              </div>

              {/* Budget */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-[var(--forge-text-muted)] mb-1.5">
                  <DollarSign className="w-3 h-3" />
                  Budget Limit (USD)
                </label>
                <input
                  value={budgetStr}
                  onChange={(e) => setBudgetStr(e.target.value)}
                  placeholder="5.00"
                  type="number"
                  step="0.50"
                  min="0"
                  className={cn(
                    "w-full px-3 py-2 rounded-lg text-sm font-mono",
                    "bg-[var(--forge-channel)] border border-[var(--forge-border)]",
                    "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                    "outline-none focus:border-[var(--forge-accent)] transition-colors"
                  )}
                />
                <p className="text-[10px] text-[var(--forge-text-muted)] mt-1">
                  Pipeline pauses for approval if budget is exceeded
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--forge-border)] shrink-0">
          <div className="flex items-center gap-3 text-[10px] text-[var(--forge-text-muted)]">
            <span>
              <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">
                {"\u2318"}Enter
              </kbd>{" "}
              to create
            </span>
            <span>
              <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">
                Esc
              </kbd>{" "}
              to cancel
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium rounded-lg text-[var(--forge-text-muted)] hover:text-white hover:bg-[var(--forge-hover)] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!spec.trim() || creating}
              className={cn(
                "flex items-center gap-2 px-5 py-2 text-xs font-medium rounded-lg transition-colors",
                spec.trim() && !creating
                  ? "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)]"
                  : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] cursor-not-allowed"
              )}
            >
              {creating ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Zap className="w-3.5 h-3.5" />
                  Start Pipeline
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
