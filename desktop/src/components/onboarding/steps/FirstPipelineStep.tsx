import { useState, useCallback, useRef, useEffect } from "react";
import { Zap, Loader2, GitBranch } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useOnboardingStore } from "@/stores/onboardingStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { STARTER_PROMPTS } from "../StarterPrompts";

export function FirstPipelineStep() {
  const { serverUrl, authToken } = useConnectionStore();
  const { selectedRepo, complete } = useOnboardingStore();
  const { addConversation, setMessages, setActiveConversation } = useConversationStore();
  const { closeSettings } = useLayoutStore();

  const [spec, setSpec] = useState("");
  const [starting, setStarting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleStartPipeline = useCallback(async () => {
    if (!spec.trim() || starting) return;
    setStarting(true);

    try {
      // Create the pipeline conversation locally
      const pipelineId = `run-${Date.now()}`;
      const convId = `pipeline-${pipelineId}`;
      const now = new Date().toISOString();

      addConversation({
        id: convId,
        type: "pipeline",
        title: spec.slice(0, 40) + (spec.length > 40 ? "..." : ""),
        pipelineId,
        participants: [{ type: "user", id: "me", name: "You" }],
        createdAt: now,
        updatedAt: now,
        unreadCount: 0,
      });

      setMessages(convId, [
        {
          id: `msg-${Date.now()}`,
          conversationId: convId,
          author: { type: "system" },
          content: [
            {
              type: "pipeline_event",
              event: "pipeline_started",
              details: {
                spec: spec.trim(),
                repo: selectedRepo?.full_name,
              },
            },
          ],
          createdAt: now,
        },
      ]);

      // Mark onboarding complete
      if (serverUrl && authToken) {
        await complete(serverUrl, authToken);
      }

      // Navigate to the new pipeline
      setActiveConversation(convId);
      closeSettings();
    } finally {
      setStarting(false);
    }
  }, [spec, starting, selectedRepo, serverUrl, authToken, complete, addConversation, setMessages, setActiveConversation, closeSettings]);

  return (
    <div className="space-y-4">
      <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
        Describe what you want to build in plain English. Your agent team will collaborate to make it happen.
      </p>

      {/* Target repo */}
      {selectedRepo && (
        <div
          className="flex items-center gap-2 text-xs px-3 py-2 rounded-lg"
          style={{ background: "var(--forge-channel)", border: "1px solid var(--forge-border)" }}
        >
          <GitBranch className="w-3 h-3" style={{ color: "var(--forge-text-muted)" }} />
          <span style={{ color: "var(--forge-text-muted)" }}>Building in:</span>
          <span className="font-medium" style={{ color: "var(--forge-text)" }}>
            {selectedRepo.full_name}
          </span>
        </div>
      )}

      {/* Spec textarea */}
      <textarea
        ref={textareaRef}
        value={spec}
        onChange={(e) => setSpec(e.target.value)}
        placeholder="e.g., Add a health check endpoint with database status, uptime tracking, and unit tests..."
        className="w-full min-h-[100px] px-3 py-2.5 rounded-lg text-sm outline-none resize-none transition-colors"
        style={{
          background: "var(--forge-channel)",
          color: "var(--forge-text)",
          border: "1px solid var(--forge-border)",
        }}
        onFocus={(e) => (e.target.style.borderColor = "var(--forge-accent)")}
        onBlur={(e) => (e.target.style.borderColor = "var(--forge-border)")}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            handleStartPipeline();
          }
        }}
      />

      {/* Starter prompts */}
      <div>
        <p className="text-xs mb-2" style={{ color: "var(--forge-text-muted)" }}>
          Or try a starter:
        </p>
        <div className="flex flex-wrap gap-2">
          {STARTER_PROMPTS.map((prompt) => (
            <button
              key={prompt.label}
              onClick={() => setSpec(prompt.spec)}
              className="px-3 py-1.5 rounded-full text-xs transition-colors cursor-pointer"
              style={{
                background: "var(--forge-channel)",
                color: "var(--forge-text-muted)",
                border: "1px solid var(--forge-border)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "var(--forge-accent)";
                e.currentTarget.style.color = "var(--forge-text)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--forge-border)";
                e.currentTarget.style.color = "var(--forge-text-muted)";
              }}
              title={prompt.description}
            >
              {prompt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Start pipeline button */}
      <button
        onClick={handleStartPipeline}
        disabled={starting || !spec.trim()}
        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ background: "var(--forge-accent)" }}
      >
        {starting ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Starting...
          </>
        ) : (
          <>
            <Zap className="w-4 h-4" />
            Start pipeline
          </>
        )}
      </button>

      <p className="text-[10px]" style={{ color: "var(--forge-text-muted)" }}>
        <kbd
          className="font-mono px-1 rounded text-[10px]"
          style={{ background: "var(--forge-hover)" }}
        >
          {"\u2318"}Enter
        </kbd>{" "}
        to start
      </p>
    </div>
  );
}
