import { AlertCircle, ArrowRight, X } from "lucide-react";
import { useOnboardingStore } from "@/stores/onboardingStore";

interface OnboardingBannerProps {
  onResume: () => void;
}

export function OnboardingBanner({ onResume }: OnboardingBannerProps) {
  const { completedCount, totalSteps, dismissBannerForSession } = useOnboardingStore();

  const completed = completedCount();
  const total = totalSteps();
  const remaining = total - completed;

  return (
    <div
      className="flex items-center gap-3 px-4 py-2 text-xs"
      style={{
        background: "var(--forge-channel)",
        borderBottom: "1px solid var(--forge-border)",
      }}
    >
      <AlertCircle className="w-3.5 h-3.5 shrink-0" style={{ color: "var(--forge-accent)" }} />
      <span style={{ color: "var(--forge-text-muted)" }}>
        Setup incomplete — {remaining} {remaining === 1 ? "step" : "steps"} remaining
      </span>
      <button
        onClick={onResume}
        className="flex items-center gap-1 font-medium transition-colors cursor-pointer"
        style={{ color: "var(--forge-accent)" }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.8")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        Resume
        <ArrowRight className="w-3 h-3" />
      </button>
      <div className="flex-1" />
      <button
        onClick={dismissBannerForSession}
        className="p-0.5 rounded transition-colors cursor-pointer"
        style={{ color: "var(--forge-text-muted)" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-text)")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
