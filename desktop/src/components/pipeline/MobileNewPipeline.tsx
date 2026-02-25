import { useState, useRef, useEffect, useCallback } from "react";
import { ArrowLeft, Zap, Mic, MicOff, Loader2, ChevronDown } from "lucide-react";
import { useHaptics } from "@/hooks/useHaptics";
import type { PipelineOptions } from "./NewPipelineModal";
import { cn } from "@/lib/utils";

// ─── Quick templates ─────────────────────────────────

const QUICK_TEMPLATES = [
  { label: "API endpoint", icon: "\u{1F310}", spec: "Build a new REST API endpoint with proper validation, error handling, and OpenAPI docs" },
  { label: "Bug fix", icon: "\u{1F41B}", spec: "Investigate and fix the bug: " },
  { label: "Refactor", icon: "\u{1F527}", spec: "Refactor the following code for better maintainability and performance: " },
  { label: "New feature", icon: "\u2728", spec: "Build a new feature: " },
];

// ─── Props ───────────────────────────────────────────

interface MobileNewPipelineProps {
  onClose: () => void;
  onCreate: (spec: string, options: PipelineOptions) => void;
}

// ─── Component ───────────────────────────────────────

export function MobileNewPipeline({ onClose, onCreate }: MobileNewPipelineProps) {
  const { haptic } = useHaptics();
  const [spec, setSpec] = useState("");
  const [repo, setRepo] = useState("");
  const [showRepoSelect, setShowRepoSelect] = useState(false);
  const [creating, setCreating] = useState(false);
  const [listening, setListening] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  // Auto-focus the textarea
  useEffect(() => {
    setTimeout(() => textareaRef.current?.focus(), 100);
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 120)}px`;
  }, [spec]);

  // ── Voice input ────────────────────────────────

  const hasSpeechRecognition =
    typeof window !== "undefined" &&
    ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const toggleVoiceInput = useCallback(() => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    let finalTranscript = spec;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += (finalTranscript ? " " : "") + transcript;
          setSpec(finalTranscript);
        } else {
          interim = transcript;
        }
      }
      // Show interim results
      if (interim) {
        setSpec(finalTranscript + (finalTranscript ? " " : "") + interim);
      }
    };

    recognition.onerror = () => {
      setListening(false);
    };

    recognition.onend = () => {
      setListening(false);
    };

    recognition.start();
    recognitionRef.current = recognition;
    setListening(true);
    haptic("light");
  }, [listening, spec]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
    };
  }, []);

  // ── Template select ────────────────────────────

  const applyTemplate = useCallback((template: typeof QUICK_TEMPLATES[0]) => {
    setSpec(template.spec);
    haptic("light");
    // Focus the textarea at the end of the template text
    setTimeout(() => {
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.selectionStart = el.selectionEnd = template.spec.length;
      }
    }, 50);
  }, []);

  // ── Create pipeline ────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!spec.trim() || creating) return;

    haptic("heavy");
    setCreating(true);

    const options: PipelineOptions = {};
    if (repo.trim()) options.repo = repo.trim();

    onCreate(spec.trim(), options);
  }, [spec, repo, creating, onCreate]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--forge-bg)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 shrink-0 border-b border-[var(--forge-border)] pt-[env(safe-area-inset-top)]">
        <button
          onClick={onClose}
          aria-label="Cancel new pipeline"
          className="flex items-center gap-1 py-3 text-[var(--forge-accent)] text-sm active:opacity-60"
        >
          <ArrowLeft className="w-4 h-4" />
          Cancel
        </button>
        <h3 className="text-sm font-semibold text-white">New Pipeline</h3>
        <button
          onClick={handleCreate}
          disabled={!spec.trim() || creating}
          className={cn(
            "py-3 text-sm font-semibold",
            spec.trim() && !creating
              ? "text-[var(--forge-accent)] active:opacity-60"
              : "text-[var(--forge-text-muted)]",
          )}
        >
          {creating ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            "Start"
          )}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {/* Quick templates */}
        <div className="px-4 pt-4 pb-2">
          <p className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2.5">
            Quick start
          </p>
          <div className="flex gap-2 overflow-x-auto pb-1 -mx-4 px-4">
            {QUICK_TEMPLATES.map((t) => (
              <button
                key={t.label}
                onClick={() => applyTemplate(t)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-[var(--forge-sidebar)] border border-[var(--forge-border)] text-xs text-[var(--forge-text)] whitespace-nowrap shrink-0 active:bg-[var(--forge-hover)]"
              >
                <span>{t.icon}</span>
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Spec textarea */}
        <div className="px-4 pt-3">
          <label className="block text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider mb-2">
            What do you want to build?
          </label>
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={spec}
              onChange={(e) => setSpec(e.target.value)}
              placeholder="Describe what you want to build... e.g., 'Build an invoice management system with PDF generation and Stripe integration'"
              className={cn(
                "w-full min-h-[120px] px-4 py-3 rounded-xl",
                "bg-[var(--forge-sidebar)] border border-[var(--forge-border)]",
                "text-sm text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                "resize-none outline-none",
                "focus:border-[var(--forge-accent)] transition-colors",
                listening && "border-[var(--forge-error)] bg-[var(--forge-error)]/5",
              )}
            />

            {/* Voice input button */}
            {hasSpeechRecognition && (
              <button
                onClick={toggleVoiceInput}
                className={cn(
                  "absolute bottom-3 right-3 p-2 rounded-full transition-colors",
                  listening
                    ? "bg-[var(--forge-error)] text-white animate-pulse"
                    : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] active:bg-[var(--forge-border)]",
                )}
              >
                {listening ? (
                  <MicOff className="w-4 h-4" />
                ) : (
                  <Mic className="w-4 h-4" />
                )}
              </button>
            )}
          </div>

          {listening && (
            <p className="text-xs text-[var(--forge-error)] mt-1.5 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[var(--forge-error)] animate-pulse" />
              Listening... speak your pipeline description
            </p>
          )}

          <p className="text-[10px] text-[var(--forge-text-muted)] mt-2">
            Be as detailed as possible. The BA will refine requirements, but a
            good spec leads to better results.
          </p>
        </div>

        {/* Optional: repo select */}
        <div className="px-4 pt-5">
          <button
            onClick={() => setShowRepoSelect(!showRepoSelect)}
            className="flex items-center gap-2 text-xs text-[var(--forge-accent)] active:opacity-60"
          >
            <ChevronDown className={cn("w-3.5 h-3.5 transition-transform", showRepoSelect && "rotate-180")} />
            {showRepoSelect ? "Hide" : "Choose"} target repo
          </button>

          {showRepoSelect && (
            <input
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              placeholder="org/repo-name"
              className={cn(
                "w-full mt-2 px-3 py-2.5 rounded-xl text-sm",
                "bg-[var(--forge-sidebar)] border border-[var(--forge-border)]",
                "text-[var(--forge-text)] placeholder:text-[var(--forge-text-muted)]/50",
                "outline-none focus:border-[var(--forge-accent)] transition-colors",
              )}
            />
          )}
        </div>
      </div>

      {/* Bottom action — large start button */}
      <div className="px-4 pt-3 pb-4 shrink-0" style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)" }}>
        <button
          onClick={handleCreate}
          disabled={!spec.trim() || creating}
          className={cn(
            "w-full flex items-center justify-center gap-2 py-4 rounded-xl",
            "text-sm font-semibold transition-all min-h-[52px]",
            spec.trim() && !creating
              ? "bg-[var(--forge-accent)] text-white active:opacity-80"
              : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)]",
          )}
        >
          {creating ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Starting pipeline...
            </>
          ) : (
            <>
              <Zap className="w-5 h-5" />
              Start Pipeline
            </>
          )}
        </button>
      </div>
    </div>
  );
}
