import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PipelineSummaryCard } from "@/components/pipeline/PipelineSummaryCard";

const MOCK_DATA = {
  type: "pipeline_summary" as const,
  pipelineId: "pipe-1",
  totalCost: 0.35,
  totalDuration: 120,
  perAgent: {
    ba: { cost: 0.04, duration: 12, firstPass: true, attempts: 1, lessonsApplied: 0 },
    researcher: {
      cost: 0.08,
      duration: 25,
      firstPass: true,
      attempts: 1,
      lessonsApplied: 1,
    },
    architect: {
      cost: 0.1,
      duration: 30,
      firstPass: false,
      attempts: 2,
      lessonsApplied: 0,
    },
    engineer: {
      cost: 0.12,
      duration: 45,
      firstPass: true,
      attempts: 1,
      lessonsApplied: 1,
    },
  },
  lessonsApplied: [
    { agentRole: "researcher", lesson: "Always check recent trends" },
    { agentRole: "engineer", lesson: "Use TypeScript strict mode" },
  ],
};

describe("PipelineSummaryCard", () => {
  it("renders cost breakdown", () => {
    render(<PipelineSummaryCard data={MOCK_DATA} />);

    expect(screen.getByText("Pipeline Complete")).toBeTruthy();
    expect(screen.getByText("$0.3500")).toBeTruthy();

    // Check per-agent costs are shown
    expect(screen.getByText("$0.040")).toBeTruthy();
    expect(screen.getByText("$0.080")).toBeTruthy();
    expect(screen.getByText("$0.100")).toBeTruthy();
    expect(screen.getByText("$0.120")).toBeTruthy();
  });

  it("shows first-pass vs revised", () => {
    render(<PipelineSummaryCard data={MOCK_DATA} />);

    const firstPassBadges = screen.getAllByText("First pass");
    const revisedBadges = screen.getAllByText("Revised");

    // 3 agents got first pass, 1 revised
    expect(firstPassBadges).toHaveLength(3);
    expect(revisedBadges).toHaveLength(1);
  });

  it("lessons section collapsible", () => {
    render(<PipelineSummaryCard data={MOCK_DATA} />);

    // Lessons toggle should be visible
    expect(screen.getByText("2 lessons applied")).toBeTruthy();

    // Initially collapsed - lesson text should not be visible
    expect(screen.queryByText("Always check recent trends")).toBeNull();

    // Click to expand
    fireEvent.click(screen.getByText("2 lessons applied"));

    // Now visible
    expect(screen.getByText("Always check recent trends")).toBeTruthy();
    expect(screen.getByText("Use TypeScript strict mode")).toBeTruthy();
  });
});
