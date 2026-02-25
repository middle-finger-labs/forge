import { useState, useCallback, useRef } from "react";
import { X, Copy, Check, Share2 } from "lucide-react";

// ─── Props ──────────────────────────────────────────

interface MobileCodeViewerProps {
  code: string;
  language: string;
  filename?: string;
  onClose: () => void;
}

// ─── Component ──────────────────────────────────────

export function MobileCodeViewer({
  code,
  language,
  filename,
  onClose,
}: MobileCodeViewerProps) {
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLPreElement>(null);
  const lines = code.split("\n");

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  const handleShare = useCallback(async () => {
    try {
      if (navigator.share) {
        await navigator.share({
          title: filename ?? `${language} code`,
          text: code,
        });
      } else {
        // Fallback to copy
        handleCopy();
      }
    } catch {
      // User cancelled share
    }
  }, [code, filename, language, handleCopy]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--forge-bg)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 shrink-0 border-b border-[var(--forge-border)] pt-[env(safe-area-inset-top)]">
        <div className="py-3 min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-white truncate">
            {filename ?? language}
          </h3>
          <p className="text-[11px] text-[var(--forge-text-muted)]">
            {lines.length} lines &middot; {language}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleShare}
            className="p-2 rounded-md text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)]"
          >
            <Share2 className="w-5 h-5" />
          </button>
          <button
            onClick={handleCopy}
            className="p-2 rounded-md text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)]"
          >
            {copied ? (
              <Check className="w-5 h-5 text-[var(--forge-success)]" />
            ) : (
              <Copy className="w-5 h-5" />
            )}
          </button>
          <button
            onClick={onClose}
            className="p-2 rounded-md text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)]"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Code content — scrollable in both directions, pinch-to-zoom via touch-action */}
      <pre
        ref={scrollRef}
        className="flex-1 overflow-auto p-4"
        style={{ touchAction: "manipulation" }}
      >
        <code className="text-[13px] font-mono leading-6 text-[var(--forge-text)]">
          {lines.map((line, i) => (
            <div key={i} className="flex">
              <span className="inline-block w-10 shrink-0 text-right pr-4 text-[var(--forge-text-muted)]/50 select-none text-xs leading-6">
                {i + 1}
              </span>
              <span className="flex-1 whitespace-pre">{line}</span>
            </div>
          ))}
        </code>
      </pre>

      {/* Bottom safe area */}
      <div className="shrink-0" style={{ height: "env(safe-area-inset-bottom)" }} />
    </div>
  );
}
