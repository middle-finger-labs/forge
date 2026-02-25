import { useState, useEffect, useCallback, useRef } from "react";
import { Play, Save, Loader2 } from "lucide-react";
import type { AgentRole } from "@/types/agent";
import type {
  PromptVersion,
  PromptVersionStats,
  StatsHistoryPoint,
  TestPromptResult,
} from "@/types/prompts";
import { getForgeAPI } from "@/services/api";
import { MiniLineChart } from "./MiniLineChart";
import { PromptDiffView } from "./PromptDiffView";

// Stage number for each agent role
const ROLE_STAGE: Record<AgentRole, number> = {
  ba: 1,
  researcher: 2,
  architect: 3,
  pm: 4,
  engineer: 5,
  qa: 6,
  cto: 7,
};

export function PromptLabTab({ role }: { role: AgentRole }) {
  const stage = ROLE_STAGE[role];

  const [editorText, setEditorText] = useState("");
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<PromptVersion | null>(null);
  const [activeStats, setActiveStats] = useState<PromptVersionStats | null>(null);
  const [statsHistory, setStatsHistory] = useState<StatsHistoryPoint[]>([]);
  const [compareVersion, setCompareVersion] = useState<PromptVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestPromptResult | null>(null);
  const [changeSummary, setChangeSummary] = useState("");
  const [showSaveForm, setShowSaveForm] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  // Load versions + defaults on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const api = await getForgeAPI();
        const vers = await api.getPromptVersions(stage);
        if (cancelled) return;
        setVersions(vers);

        const active = vers.find((v) => v.is_active);
        if (active) {
          setEditorText(active.system_prompt);
          setSelectedVersion(active);
          // Load stats
          const [stats, history] = await Promise.all([
            api.getPromptVersionStats(active.id),
            api.getPromptVersionStatsHistory(active.id),
          ]);
          if (!cancelled) {
            setActiveStats(stats);
            setStatsHistory(history);
          }
        } else {
          // Load default prompt
          const defaults = await api.getDefaultPrompts();
          const def = defaults.find((d) => d.stage === stage);
          if (def && !cancelled) {
            setEditorText(def.preview.endsWith("...") ? def.preview : def.preview);
          }
        }
      } catch (err) {
        console.error("Failed to load prompt versions", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [stage]);

  const handleSelectVersion = useCallback(async (v: PromptVersion) => {
    setSelectedVersion(v);
    setEditorText(v.system_prompt);
    setCompareVersion(null);
    try {
      const api = await getForgeAPI();
      const [stats, history] = await Promise.all([
        api.getPromptVersionStats(v.id),
        api.getPromptVersionStatsHistory(v.id),
      ]);
      setActiveStats(stats);
      setStatsHistory(history);
    } catch { /* ignore */ }
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const api = await getForgeAPI();
      const newVer = await api.createPromptVersion({
        stage,
        system_prompt: editorText,
        change_summary: changeSummary,
        activate: false,
      });
      setVersions((prev) => [newVer, ...prev]);
      setSelectedVersion(newVer);
      setChangeSummary("");
      setShowSaveForm(false);
    } catch (err) {
      console.error("Failed to save version", err);
    } finally {
      setSaving(false);
    }
  }, [stage, editorText, changeSummary]);

  const handleActivate = useCallback(async () => {
    if (!selectedVersion) return;
    try {
      const api = await getForgeAPI();
      await api.activatePromptVersion(selectedVersion.id);
      setVersions((prev) =>
        prev.map((v) => ({
          ...v,
          is_active: v.id === selectedVersion.id,
        }))
      );
      setSelectedVersion((v) => v ? { ...v, is_active: true } : v);
    } catch (err) {
      console.error("Failed to activate version", err);
    }
  }, [selectedVersion]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const api = await getForgeAPI();
      const result = await api.testPrompt(stage, editorText);
      setTestResult(result);
    } catch (err) {
      setTestResult({
        output: null,
        cost_usd: 0,
        duration_seconds: 0,
        error: String(err),
      });
    } finally {
      setTesting(false);
    }
  }, [stage, editorText]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2
          className="w-5 h-5 animate-spin"
          style={{ color: "var(--forge-text-muted)" }}
        />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-5 gap-4 pt-2" style={{ minHeight: 400 }}>
      {/* Left column — editor (3/5) */}
      <div className="col-span-3 flex flex-col gap-3">
        {/* Editor */}
        <div className="relative flex-1 min-h-[240px]">
          {/* Highlight layer */}
          <div
            className="absolute inset-0 pointer-events-none p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words overflow-hidden"
            style={{ color: "transparent" }}
            aria-hidden
          >
            {highlightVariables(editorText)}
          </div>
          <textarea
            ref={editorRef}
            value={editorText}
            onChange={(e) => setEditorText(e.target.value)}
            className="w-full h-full p-3 font-mono text-xs leading-5 rounded-lg resize-none outline-none"
            style={{
              background: "var(--forge-bg)",
              color: "var(--forge-text)",
              border: "1px solid var(--forge-border)",
              caretColor: "var(--forge-accent)",
            }}
            spellCheck={false}
          />
        </div>

        {/* Actions bar */}
        <div className="flex items-center gap-2">
          {showSaveForm ? (
            <div className="flex items-center gap-2 flex-1">
              <input
                value={changeSummary}
                onChange={(e) => setChangeSummary(e.target.value)}
                placeholder="What changed?"
                className="flex-1 px-2 py-1 rounded text-xs outline-none"
                style={{
                  background: "var(--forge-bg)",
                  color: "var(--forge-text)",
                  border: "1px solid var(--forge-border)",
                }}
              />
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                style={{
                  background: "var(--forge-accent)",
                  color: "#fff",
                }}
              >
                {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                Save
              </button>
              <button
                onClick={() => setShowSaveForm(false)}
                className="px-2 py-1 rounded text-xs cursor-pointer"
                style={{ color: "var(--forge-text-muted)" }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <>
              <button
                onClick={() => setShowSaveForm(true)}
                className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium transition-colors cursor-pointer"
                style={{
                  background: "var(--forge-channel)",
                  color: "var(--forge-text)",
                  border: "1px solid var(--forge-border)",
                }}
              >
                <Save className="w-3 h-3" />
                Save as new version
              </button>
              {selectedVersion && !selectedVersion.is_active && (
                <button
                  onClick={handleActivate}
                  className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
                  style={{
                    background: "var(--forge-success)",
                    color: "#fff",
                  }}
                >
                  Activate
                </button>
              )}
              <button
                onClick={handleTest}
                disabled={testing}
                className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                style={{
                  background: "var(--forge-accent)",
                  color: "#fff",
                }}
              >
                {testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                Test this prompt
              </button>
            </>
          )}
        </div>

        {/* Test result */}
        {testResult && (
          <div
            className="rounded-lg p-3 text-xs"
            style={{
              background: "var(--forge-bg)",
              border: `1px solid ${testResult.error ? "var(--forge-error)" : "var(--forge-border)"}`,
            }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium" style={{ color: "var(--forge-text)" }}>
                Test Result
              </span>
              <span style={{ color: "var(--forge-text-muted)" }}>
                ${testResult.cost_usd.toFixed(4)} &middot; {testResult.duration_seconds}s
              </span>
            </div>
            {testResult.error ? (
              <pre
                className="whitespace-pre-wrap"
                style={{ color: "var(--forge-error)" }}
              >
                {testResult.error}
              </pre>
            ) : (
              <pre
                className="whitespace-pre-wrap max-h-48 overflow-y-auto"
                style={{ color: "var(--forge-text)" }}
              >
                {JSON.stringify(testResult.output, null, 2)}
              </pre>
            )}
          </div>
        )}

        {/* Diff view (when comparing) */}
        {compareVersion && selectedVersion && (
          <PromptDiffView
            leftText={compareVersion.system_prompt}
            rightText={selectedVersion.system_prompt}
            leftLabel={`v${compareVersion.version}`}
            rightLabel={`v${selectedVersion.version}`}
          />
        )}
      </div>

      {/* Right column — versions + stats (2/5) */}
      <div className="col-span-2 flex flex-col gap-3">
        {/* Version history */}
        <div
          className="rounded-lg overflow-hidden"
          style={{ border: "1px solid var(--forge-border)" }}
        >
          <div
            className="px-3 py-2 text-xs font-medium"
            style={{
              background: "var(--forge-bg)",
              color: "var(--forge-text-muted)",
              borderBottom: "1px solid var(--forge-border)",
            }}
          >
            Version History ({versions.length})
          </div>
          <div className="max-h-48 overflow-y-auto">
            {versions.map((v) => (
              <button
                key={v.id}
                onClick={() => handleSelectVersion(v)}
                onDoubleClick={() =>
                  setCompareVersion(
                    compareVersion?.id === v.id ? null : v
                  )
                }
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors cursor-pointer"
                style={{
                  background:
                    selectedVersion?.id === v.id
                      ? "var(--forge-hover)"
                      : "transparent",
                  borderBottom: "1px solid var(--forge-border)",
                }}
              >
                <span
                  className="font-mono font-medium shrink-0"
                  style={{ color: "var(--forge-text)" }}
                >
                  v{v.version}
                </span>
                <span
                  className="truncate flex-1"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  {v.change_summary || "No summary"}
                </span>
                {v.is_active && (
                  <span
                    className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium"
                    style={{
                      background: "var(--forge-success)",
                      color: "#fff",
                    }}
                  >
                    Active
                  </span>
                )}
              </button>
            ))}
            {versions.length === 0 && (
              <div
                className="px-3 py-4 text-xs text-center"
                style={{ color: "var(--forge-text-muted)" }}
              >
                No custom versions yet. Edit the prompt and save.
              </div>
            )}
          </div>
        </div>

        {/* Stats dashboard */}
        {activeStats && activeStats.total_runs > 0 && (
          <div
            className="rounded-lg p-3 space-y-3"
            style={{
              background: "var(--forge-bg)",
              border: "1px solid var(--forge-border)",
            }}
          >
            <div
              className="text-xs font-medium"
              style={{ color: "var(--forge-text-muted)" }}
            >
              Performance
            </div>
            <div className="grid grid-cols-2 gap-2">
              <StatCard label="Runs" value={String(activeStats.total_runs)} />
              <StatCard
                label="Approval"
                value={`${(activeStats.approval_rate * 100).toFixed(0)}%`}
                color={
                  activeStats.approval_rate >= 0.8
                    ? "var(--forge-success)"
                    : activeStats.approval_rate >= 0.5
                      ? "var(--forge-warning)"
                      : "var(--forge-error)"
                }
              />
              <StatCard
                label="Avg Cost"
                value={`$${activeStats.avg_cost_usd.toFixed(3)}`}
              />
              <StatCard
                label="Avg Attempts"
                value={activeStats.avg_attempts.toFixed(1)}
              />
            </div>

            {/* Approval rate chart */}
            {statsHistory.length >= 2 && (
              <div>
                <div
                  className="text-[10px] mb-1"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  Approval Rate Trend
                </div>
                <MiniLineChart
                  data={statsHistory.map((h) => ({
                    label: h.date,
                    value: h.approval_rate * 100,
                  }))}
                  height={100}
                  formatValue={(v) => `${v.toFixed(0)}%`}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div
      className="rounded-md px-2 py-1.5"
      style={{
        background: "var(--forge-channel)",
        border: "1px solid var(--forge-border)",
      }}
    >
      <div className="text-[10px]" style={{ color: "var(--forge-text-muted)" }}>
        {label}
      </div>
      <div
        className="text-sm font-mono font-semibold"
        style={{ color: color ?? "var(--forge-text)" }}
      >
        {value}
      </div>
    </div>
  );
}

/** Render text with {variable_name} spans highlighted */
function highlightVariables(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const regex = /\{(\w+)\}/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(
      <span key={match.index} style={{ color: "var(--forge-accent)" }}>
        {match[0]}
      </span>
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}
