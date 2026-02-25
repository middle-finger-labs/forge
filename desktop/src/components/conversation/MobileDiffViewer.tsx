import { useState, useCallback } from "react";
import { X, Copy, Check, Columns2, AlignJustify } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Props ──────────────────────────────────────────

interface MobileDiffViewerProps {
  diff: string;
  filename: string;
  onClose: () => void;
}

// ─── Types ──────────────────────────────────────────

interface DiffLine {
  type: "add" | "remove" | "context" | "header";
  content: string;
  oldLineNo?: number;
  newLineNo?: number;
}

// ─── Component ──────────────────────────────────────

export function MobileDiffViewer({
  diff,
  filename,
  onClose,
}: MobileDiffViewerProps) {
  const [viewMode, setViewMode] = useState<"unified" | "split">("unified");
  const [copied, setCopied] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Set<number>>(new Set());

  const lines = parseDiff(diff);
  const additions = lines.filter((l) => l.type === "add").length;
  const deletions = lines.filter((l) => l.type === "remove").length;

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(diff);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [diff]);

  // Group context lines into collapsible sections
  const sections = groupContextSections(lines);

  const toggleSection = useCallback((idx: number) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--forge-bg)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 shrink-0 border-b border-[var(--forge-border)] pt-[env(safe-area-inset-top)]">
        <div className="py-3 min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-white truncate">{filename}</h3>
          <div className="flex items-center gap-3 text-[11px]">
            <span className="text-[var(--forge-success)]">+{additions}</span>
            <span className="text-[var(--forge-error)]">-{deletions}</span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {/* View mode toggle */}
          <button
            onClick={() => setViewMode(viewMode === "unified" ? "split" : "unified")}
            className={cn(
              "p-2 rounded-md active:bg-[var(--forge-hover)]",
              "text-[var(--forge-text-muted)]"
            )}
            title={viewMode === "unified" ? "Split view" : "Unified view"}
          >
            {viewMode === "unified" ? (
              <Columns2 className="w-5 h-5" />
            ) : (
              <AlignJustify className="w-5 h-5" />
            )}
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

      {/* Diff content */}
      <div className="flex-1 overflow-auto">
        {viewMode === "unified" ? (
          <UnifiedDiffView
            sections={sections}
            collapsedSections={collapsedSections}
            onToggleSection={toggleSection}
          />
        ) : (
          <SplitDiffView lines={lines} />
        )}
      </div>

      {/* Bottom safe area */}
      <div className="shrink-0" style={{ height: "env(safe-area-inset-bottom)" }} />
    </div>
  );
}

// ─── Unified view ───────────────────────────────────

function UnifiedDiffView({
  sections,
  collapsedSections,
  onToggleSection,
}: {
  sections: DiffSection[];
  collapsedSections: Set<number>;
  onToggleSection: (idx: number) => void;
}) {
  return (
    <pre className="p-0 text-[13px] font-mono leading-6">
      {sections.map((section, sIdx) => {
        if (section.type === "context" && section.lines.length > 6) {
          const isCollapsed = !collapsedSections.has(sIdx);
          return (
            <div key={sIdx}>
              {isCollapsed ? (
                <button
                  onClick={() => onToggleSection(sIdx)}
                  className="w-full py-1 text-center text-[11px] text-[var(--forge-text-muted)] bg-[var(--forge-hover)]/50 active:bg-[var(--forge-hover)]"
                >
                  {section.lines.length} unchanged lines — tap to expand
                </button>
              ) : (
                <>
                  {section.lines.map((line, i) => (
                    <DiffLineRow key={`${sIdx}-${i}`} line={line} />
                  ))}
                  <button
                    onClick={() => onToggleSection(sIdx)}
                    className="w-full py-1 text-center text-[11px] text-[var(--forge-text-muted)] bg-[var(--forge-hover)]/50 active:bg-[var(--forge-hover)]"
                  >
                    Collapse
                  </button>
                </>
              )}
            </div>
          );
        }
        return (
          <div key={sIdx}>
            {section.lines.map((line, i) => (
              <DiffLineRow key={`${sIdx}-${i}`} line={line} />
            ))}
          </div>
        );
      })}
    </pre>
  );
}

function DiffLineRow({ line }: { line: DiffLine }) {
  return (
    <div
      className={cn(
        "flex px-2",
        line.type === "add" && "bg-[var(--forge-success)]/8",
        line.type === "remove" && "bg-[var(--forge-error)]/8"
      )}
    >
      <span className="w-8 shrink-0 text-right pr-2 text-[var(--forge-text-muted)]/40 select-none text-[11px] leading-6">
        {line.oldLineNo ?? ""}
      </span>
      <span className="w-8 shrink-0 text-right pr-2 text-[var(--forge-text-muted)]/40 select-none text-[11px] leading-6">
        {line.newLineNo ?? ""}
      </span>
      <span
        className={cn(
          "flex-1 whitespace-pre overflow-x-auto",
          line.type === "add" && "text-[var(--forge-success)]",
          line.type === "remove" && "text-[var(--forge-error)]",
          line.type === "context" && "text-[var(--forge-text-muted)]",
          line.type === "header" && "text-[var(--forge-accent)] font-medium"
        )}
      >
        {line.content}
      </span>
    </div>
  );
}

// ─── Split view ─────────────────────────────────────

function SplitDiffView({ lines }: { lines: DiffLine[] }) {
  const leftLines = lines.filter((l) => l.type !== "add");
  const rightLines = lines.filter((l) => l.type !== "remove");

  return (
    <div className="flex overflow-x-auto">
      <div className="flex-1 min-w-0 border-r border-[var(--forge-border)]">
        <pre className="p-0 text-[12px] font-mono leading-6">
          {leftLines.map((line, i) => (
            <div
              key={i}
              className={cn(
                "px-2 whitespace-pre",
                line.type === "remove" && "bg-[var(--forge-error)]/8 text-[var(--forge-error)]",
                line.type === "context" && "text-[var(--forge-text-muted)]",
                line.type === "header" && "text-[var(--forge-accent)]"
              )}
            >
              {line.content}
            </div>
          ))}
        </pre>
      </div>
      <div className="flex-1 min-w-0">
        <pre className="p-0 text-[12px] font-mono leading-6">
          {rightLines.map((line, i) => (
            <div
              key={i}
              className={cn(
                "px-2 whitespace-pre",
                line.type === "add" && "bg-[var(--forge-success)]/8 text-[var(--forge-success)]",
                line.type === "context" && "text-[var(--forge-text-muted)]",
                line.type === "header" && "text-[var(--forge-accent)]"
              )}
            >
              {line.content}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

// ─── Diff parsing ───────────────────────────────────

interface DiffSection {
  type: "context" | "changes";
  lines: DiffLine[];
}

function parseDiff(raw: string): DiffLine[] {
  const lines = raw.split("\n");
  let oldLine = 0;
  let newLine = 0;

  return lines.map((content) => {
    if (content.startsWith("@@")) {
      const match = content.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldLine = parseInt(match[1], 10);
        newLine = parseInt(match[2], 10);
      }
      return { type: "header" as const, content };
    }
    if (content.startsWith("+")) {
      const line: DiffLine = { type: "add", content, newLineNo: newLine };
      newLine++;
      return line;
    }
    if (content.startsWith("-")) {
      const line: DiffLine = { type: "remove", content, oldLineNo: oldLine };
      oldLine++;
      return line;
    }
    const line: DiffLine = { type: "context", content, oldLineNo: oldLine, newLineNo: newLine };
    oldLine++;
    newLine++;
    return line;
  });
}

function groupContextSections(lines: DiffLine[]): DiffSection[] {
  const sections: DiffSection[] = [];
  let current: DiffSection | null = null;

  for (const line of lines) {
    const sectionType = line.type === "context" ? "context" : "changes";
    if (!current || current.type !== sectionType) {
      current = { type: sectionType, lines: [] };
      sections.push(current);
    }
    current.lines.push(line);
  }

  return sections;
}
