import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PromptLabTab } from "@/components/settings/tabs/PromptLabTab";

// Mock the API
const mockGetPromptVersions = vi.fn();
const mockGetDefaultPrompts = vi.fn();
const mockGetPromptVersionStats = vi.fn();
const mockGetPromptVersionStatsHistory = vi.fn();
const mockCreatePromptVersion = vi.fn();
const mockTestPrompt = vi.fn();
const mockActivatePromptVersion = vi.fn();

vi.mock("@/services/api", () => ({
  getForgeAPI: vi.fn(async () => ({
    getPromptVersions: mockGetPromptVersions,
    getDefaultPrompts: mockGetDefaultPrompts,
    getPromptVersionStats: mockGetPromptVersionStats,
    getPromptVersionStatsHistory: mockGetPromptVersionStatsHistory,
    createPromptVersion: mockCreatePromptVersion,
    testPrompt: mockTestPrompt,
    activatePromptVersion: mockActivatePromptVersion,
  })),
}));

const MOCK_VERSIONS = [
  {
    id: "v-1",
    org_id: "org-1",
    stage: 1,
    agent_role: "business_analyst",
    version: 2,
    system_prompt: "You are a great BA agent v2.",
    change_summary: "Improved instructions",
    is_active: true,
    created_by: "user-1",
    created_at: "2025-01-01T00:00:00Z",
    prompt_hash: "abc123",
  },
  {
    id: "v-0",
    org_id: "org-1",
    stage: 1,
    agent_role: "business_analyst",
    version: 1,
    system_prompt: "You are a BA agent v1.",
    change_summary: "Initial version",
    is_active: false,
    created_by: "user-1",
    created_at: "2024-12-01T00:00:00Z",
    prompt_hash: "def456",
  },
];

const MOCK_STATS = {
  version_id: "v-1",
  total_runs: 10,
  approval_rate: 0.8,
  avg_cost_usd: 0.045,
  avg_duration_seconds: 15.3,
  avg_attempts: 1.2,
  error_count: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGetPromptVersions.mockResolvedValue(MOCK_VERSIONS);
  mockGetPromptVersionStats.mockResolvedValue(MOCK_STATS);
  mockGetPromptVersionStatsHistory.mockResolvedValue([]);
  mockGetDefaultPrompts.mockResolvedValue([]);
});

describe("PromptLabTab", () => {
  it("renders editor with active prompt", async () => {
    render(<PromptLabTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("You are a great BA agent v2.")).toBeTruthy();
    });
  });

  it("version history loads and displays", async () => {
    render(<PromptLabTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Version History (2)")).toBeTruthy();
    });

    expect(screen.getByText("v2")).toBeTruthy();
    expect(screen.getByText("v1")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
  });

  it("clicking version loads into editor", async () => {
    render(<PromptLabTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("v1")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("v1"));

    await waitFor(() => {
      expect(
        screen.getByDisplayValue("You are a BA agent v1.")
      ).toBeTruthy();
    });
  });

  it("save creates new version", async () => {
    const newVersion = {
      ...MOCK_VERSIONS[0],
      id: "v-2",
      version: 3,
      change_summary: "Test change",
    };
    mockCreatePromptVersion.mockResolvedValue(newVersion);

    render(<PromptLabTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Save as new version")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Save as new version"));

    const input = screen.getByPlaceholderText("What changed?");
    fireEvent.change(input, { target: { value: "Test change" } });

    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockCreatePromptVersion).toHaveBeenCalledWith({
        stage: 1,
        system_prompt: "You are a great BA agent v2.",
        change_summary: "Test change",
        activate: false,
      });
    });
  });

  it("test prompt shows result", async () => {
    mockTestPrompt.mockResolvedValue({
      output: { name: "Test Product" },
      cost_usd: 0.05,
      duration_seconds: 12,
      error: null,
    });

    render(<PromptLabTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Test this prompt")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Test this prompt"));

    await waitFor(() => {
      expect(screen.getByText("Test Result")).toBeTruthy();
    });

    expect(screen.getByText(/\$0\.0500/)).toBeTruthy();
  });
});
