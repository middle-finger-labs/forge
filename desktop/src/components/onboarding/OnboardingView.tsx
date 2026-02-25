import { useCallback, useEffect, useRef } from "react";
import { Check, ChevronDown, Key, Github, Users, Zap } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useOnboardingStore, type OnboardingStepName } from "@/stores/onboardingStore";
import { ApiKeyStep } from "./steps/ApiKeyStep";
import { GitHubStep } from "./steps/GitHubStep";
import { MeetTeamStep } from "./steps/MeetTeamStep";
import { FirstPipelineStep } from "./steps/FirstPipelineStep";

// ─── Step definitions ─────────────────────────────────

interface StepDef {
  key: OnboardingStepName;
  label: string;
  icon: typeof Key;
}

const STEP_DEFS: StepDef[] = [
  { key: "api_key", label: "Add your Anthropic API key", icon: Key },
  { key: "github", label: "Connect GitHub", icon: Github },
  { key: "meet_team", label: "Meet your agents", icon: Users },
  { key: "first_pipeline", label: "Start your first pipeline", icon: Zap },
];

const STEP_COMPONENTS: Record<OnboardingStepName, React.FC> = {
  api_key: ApiKeyStep,
  github: GitHubStep,
  meet_team: MeetTeamStep,
  first_pipeline: FirstPipelineStep,
};

// ─── OnboardingView ───────────────────────────────────

export function OnboardingView() {
  const { serverUrl, authToken } = useConnectionStore();
  const { steps, expandedStep, setExpandedStep, dismiss, completedCount, totalSteps } =
    useOnboardingStore();

  // Auto-expand first incomplete step on mount
  const hasAutoExpanded = useRef(false);
  useEffect(() => {
    if (hasAutoExpanded.current) return;
    const firstIncomplete = STEP_DEFS.find((d) => !steps[d.key]);
    if (firstIncomplete) {
      setExpandedStep(firstIncomplete.key);
      hasAutoExpanded.current = true;
    }
  }, [steps, setExpandedStep]);

  // Auto-advance to next incomplete step when a step completes
  const prevStepsRef = useRef(steps);
  useEffect(() => {
    const prev = prevStepsRef.current;
    prevStepsRef.current = steps;

    // Check if any step just flipped from false to true
    const justCompleted = STEP_DEFS.some((d) => steps[d.key] && !prev[d.key]);
    if (!justCompleted) return;

    const nextIncomplete = STEP_DEFS.find((d) => !steps[d.key]);
    if (nextIncomplete) {
      setExpandedStep(nextIncomplete.key);
    } else {
      setExpandedStep(null);
    }
  }, [steps, setExpandedStep]);

  const handleSkip = useCallback(async () => {
    if (serverUrl && authToken) {
      await dismiss(serverUrl, authToken);
    }
  }, [serverUrl, authToken, dismiss]);

  const handleToggleStep = useCallback(
    (step: OnboardingStepName) => {
      setExpandedStep(expandedStep === step ? null : step);
    },
    [expandedStep, setExpandedStep]
  );

  const completed = completedCount();
  const total = totalSteps();

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-xl mx-auto py-10 px-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-lg font-semibold" style={{ color: "var(--forge-text)" }}>
            Welcome to Forge
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--forge-text-muted)" }}>
            Let's get your workspace set up. This takes about 2 minutes.
          </p>
        </div>

        {/* Progress bar */}
        <div className="mb-6">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span style={{ color: "var(--forge-text-muted)" }}>
              {completed} of {total} complete
            </span>
            {completed > 0 && completed < total && (
              <span style={{ color: "var(--forge-accent)" }}>
                {Math.round((completed / total) * 100)}%
              </span>
            )}
          </div>
          <div
            className="h-1.5 rounded-full overflow-hidden"
            style={{ background: "var(--forge-border)" }}
          >
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: `${(completed / total) * 100}%`,
                background: "var(--forge-accent)",
              }}
            />
          </div>
        </div>

        {/* Step accordion */}
        <div
          className="rounded-lg overflow-hidden"
          style={{ border: "1px solid var(--forge-border)" }}
        >
          {STEP_DEFS.map((def, i) => {
            const isComplete = steps[def.key];
            const isExpanded = expandedStep === def.key;
            const StepComponent = STEP_COMPONENTS[def.key];
            const isLast = i === STEP_DEFS.length - 1;

            return (
              <div key={def.key}>
                {/* Step header */}
                <button
                  onClick={() => handleToggleStep(def.key)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left transition-colors cursor-pointer"
                  style={{
                    background: isExpanded ? "var(--forge-channel)" : "transparent",
                    borderBottom: isLast && !isExpanded ? "none" : "1px solid var(--forge-border)",
                  }}
                  onMouseEnter={(e) => {
                    if (!isExpanded) e.currentTarget.style.background = "var(--forge-hover)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isExpanded) e.currentTarget.style.background = "transparent";
                  }}
                >
                  {/* Status indicator */}
                  <div
                    className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 transition-colors"
                    style={{
                      background: isComplete
                        ? "var(--forge-accent)"
                        : "transparent",
                      border: isComplete
                        ? "none"
                        : "2px solid var(--forge-border)",
                    }}
                  >
                    {isComplete ? (
                      <Check className="w-3.5 h-3.5 text-white" />
                    ) : (
                      <def.icon
                        className="w-3 h-3"
                        style={{ color: "var(--forge-text-muted)" }}
                      />
                    )}
                  </div>

                  {/* Label */}
                  <span
                    className="flex-1 text-sm font-medium"
                    style={{
                      color: isComplete ? "var(--forge-text-muted)" : "var(--forge-text)",
                      textDecoration: isComplete ? "line-through" : "none",
                    }}
                  >
                    {def.label}
                  </span>

                  {/* Chevron */}
                  <ChevronDown
                    className="w-4 h-4 transition-transform duration-200"
                    style={{
                      color: "var(--forge-text-muted)",
                      transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                    }}
                  />
                </button>

                {/* Step content (expanded) */}
                {isExpanded && (
                  <div
                    className="px-4 py-4"
                    style={{
                      background: "var(--forge-channel)",
                      borderBottom: isLast ? "none" : "1px solid var(--forge-border)",
                    }}
                  >
                    <StepComponent />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Skip setup */}
        <div className="mt-4 text-center">
          <button
            onClick={handleSkip}
            className="text-xs transition-colors cursor-pointer"
            style={{ color: "var(--forge-text-muted)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-text)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
          >
            Skip setup — I'll do this later
          </button>
        </div>
      </div>
    </div>
  );
}
