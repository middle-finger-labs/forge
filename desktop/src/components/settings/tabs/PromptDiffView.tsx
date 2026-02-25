import { useRef, useCallback } from "react";

interface PromptDiffViewProps {
  leftText: string;
  rightText: string;
  leftLabel: string;
  rightLabel: string;
}

type DiffLine = {
  text: string;
  type: "unchanged" | "added" | "removed";
};

/**
 * Simple LCS-based line diff. Produces two aligned column arrays.
 */
function computeDiff(
  left: string[],
  right: string[]
): { leftLines: DiffLine[]; rightLines: DiffLine[] } {
  // Build LCS table
  const m = left.length;
  const n = right.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    Array(n + 1).fill(0)
  );
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] =
        left[i - 1] === right[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }

  // Backtrack
  const leftLines: DiffLine[] = [];
  const rightLines: DiffLine[] = [];
  let i = m;
  let j = n;
  const stack: Array<[DiffLine, DiffLine]> = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && left[i - 1] === right[j - 1]) {
      stack.push([
        { text: left[i - 1], type: "unchanged" },
        { text: right[j - 1], type: "unchanged" },
      ]);
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      stack.push([
        { text: "", type: "unchanged" },
        { text: right[j - 1], type: "added" },
      ]);
      j--;
    } else {
      stack.push([
        { text: left[i - 1], type: "removed" },
        { text: "", type: "unchanged" },
      ]);
      i--;
    }
  }

  stack.reverse();
  for (const [l, r] of stack) {
    leftLines.push(l);
    rightLines.push(r);
  }

  return { leftLines, rightLines };
}

const LINE_COLORS = {
  added: "bg-[var(--forge-success)]/10",
  removed: "bg-[var(--forge-error)]/10",
  unchanged: "",
};

export function PromptDiffView({
  leftText,
  rightText,
  leftLabel,
  rightLabel,
}: PromptDiffViewProps) {
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const syncing = useRef(false);

  const { leftLines, rightLines } = computeDiff(
    leftText.split("\n"),
    rightText.split("\n")
  );

  const syncScroll = useCallback(
    (source: "left" | "right") => {
      if (syncing.current) return;
      syncing.current = true;
      const from = source === "left" ? leftRef.current : rightRef.current;
      const to = source === "left" ? rightRef.current : leftRef.current;
      if (from && to) {
        to.scrollTop = from.scrollTop;
      }
      syncing.current = false;
    },
    []
  );

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ borderColor: "var(--forge-border)" }}
    >
      {/* Header */}
      <div
        className="grid grid-cols-2 text-xs font-medium border-b"
        style={{
          borderColor: "var(--forge-border)",
          background: "var(--forge-bg)",
          color: "var(--forge-text-muted)",
        }}
      >
        <div className="px-3 py-1.5 border-r" style={{ borderColor: "var(--forge-border)" }}>
          {leftLabel}
        </div>
        <div className="px-3 py-1.5">{rightLabel}</div>
      </div>

      {/* Diff columns */}
      <div className="grid grid-cols-2 max-h-64 overflow-hidden">
        <div
          ref={leftRef}
          className="overflow-y-auto border-r font-mono text-xs"
          style={{ borderColor: "var(--forge-border)" }}
          onScroll={() => syncScroll("left")}
        >
          {leftLines.map((line, i) => (
            <div
              key={i}
              className={`flex ${LINE_COLORS[line.type]}`}
            >
              <span
                className="w-8 shrink-0 text-right pr-2 select-none"
                style={{ color: "var(--forge-text-muted)" }}
              >
                {line.text !== "" ? i + 1 : ""}
              </span>
              <span
                className="flex-1 whitespace-pre-wrap break-all px-1"
                style={{
                  color:
                    line.type === "removed"
                      ? "var(--forge-error)"
                      : "var(--forge-text)",
                }}
              >
                {line.text}
              </span>
            </div>
          ))}
        </div>
        <div
          ref={rightRef}
          className="overflow-y-auto font-mono text-xs"
          onScroll={() => syncScroll("right")}
        >
          {rightLines.map((line, i) => (
            <div
              key={i}
              className={`flex ${LINE_COLORS[line.type]}`}
            >
              <span
                className="w-8 shrink-0 text-right pr-2 select-none"
                style={{ color: "var(--forge-text-muted)" }}
              >
                {line.text !== "" ? i + 1 : ""}
              </span>
              <span
                className="flex-1 whitespace-pre-wrap break-all px-1"
                style={{
                  color:
                    line.type === "added"
                      ? "var(--forge-success)"
                      : "var(--forge-text)",
                }}
              >
                {line.text}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
