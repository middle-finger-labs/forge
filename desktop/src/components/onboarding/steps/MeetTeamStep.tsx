import { useState, useEffect, useCallback } from "react";
import { ArrowRight } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useOnboardingStore } from "@/stores/onboardingStore";

interface AgentInfo {
  emoji: string;
  name: string;
  description: string;
}

const AGENTS: AgentInfo[] = [
  {
    emoji: "\u{1F3E2}",
    name: "Business Analyst",
    description: "Turns your ideas into detailed specs. Asks the right clarifying questions so nothing gets missed.",
  },
  {
    emoji: "\u{1F52C}",
    name: "Researcher",
    description: "Investigates libraries, APIs, and best practices. Makes sure the team uses the right tools.",
  },
  {
    emoji: "\u{1F3D7}\uFE0F",
    name: "Architect",
    description: "Designs the system. Database schemas, API contracts, component structure, tech decisions.",
  },
  {
    emoji: "\u{1F4CB}",
    name: "Project Manager",
    description: "Breaks the architecture into tasks. Orders them by dependency. Keeps the pipeline moving.",
  },
  {
    emoji: "\u{1F4BB}",
    name: "Engineer",
    description: "Writes the code. Uses Claude Code under the hood. Creates branches, writes tests, pushes to GitHub.",
  },
  {
    emoji: "\u{1F9EA}",
    name: "QA Engineer",
    description: "Reviews the code. Runs tests. Finds edge cases and security issues before you ship.",
  },
  {
    emoji: "\u{1F454}",
    name: "CTO",
    description: "Final review. Evaluates architecture, code quality, and production readiness. Your last line of defense before merge.",
  },
];

export function MeetTeamStep() {
  const { serverUrl, authToken } = useConnectionStore();
  const { completeStep } = useOnboardingStore();
  const [visibleCount, setVisibleCount] = useState(0);

  // Stagger agent cards in one by one
  useEffect(() => {
    if (visibleCount < AGENTS.length) {
      const timer = setTimeout(() => setVisibleCount((c) => c + 1), 80);
      return () => clearTimeout(timer);
    }
  }, [visibleCount]);

  const handleGotIt = useCallback(async () => {
    if (serverUrl && authToken) {
      await completeStep(serverUrl, authToken, "meet_team");
    }
  }, [serverUrl, authToken, completeStep]);

  return (
    <div className="space-y-4">
      <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
        These are your AI agents. Each one has a specialty.
        You can chat with any of them directly, or they'll work together automatically in pipelines.
      </p>

      {/* Agent roster */}
      <div className="space-y-2">
        {AGENTS.map((agent, i) => (
          <div
            key={agent.name}
            className="flex items-start gap-3 p-3 rounded-lg transition-all duration-300"
            style={{
              background: "var(--forge-channel)",
              border: "1px solid var(--forge-border)",
              opacity: i < visibleCount ? 1 : 0,
              transform: i < visibleCount ? "translateY(0)" : "translateY(8px)",
            }}
          >
            <span className="text-lg shrink-0 mt-0.5">{agent.emoji}</span>
            <div>
              <div className="text-sm font-medium" style={{ color: "var(--forge-text)" }}>
                {agent.name}
              </div>
              <div className="text-xs mt-0.5" style={{ color: "var(--forge-text-muted)" }}>
                {agent.description}
              </div>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
        Tap any agent in the sidebar to start a conversation.
      </p>

      {/* Got it button */}
      <button
        onClick={handleGotIt}
        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity cursor-pointer"
        style={{ background: "var(--forge-accent)" }}
      >
        Got it
        <ArrowRight className="w-4 h-4" />
      </button>
    </div>
  );
}
