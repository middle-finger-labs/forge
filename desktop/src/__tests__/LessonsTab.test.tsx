import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LessonsTab } from "@/components/settings/tabs/LessonsTab";

const mockGetLessons = vi.fn();
const mockDeleteLesson = vi.fn();
const mockReinforceLesson = vi.fn();
const mockUpdateLesson = vi.fn();

vi.mock("@/services/api", () => ({
  getForgeAPI: vi.fn(async () => ({
    getLessons: mockGetLessons,
    deleteLesson: mockDeleteLesson,
    reinforceLesson: mockReinforceLesson,
    updateLesson: mockUpdateLesson,
  })),
}));

const MOCK_LESSONS = [
  {
    id: "l-1",
    org_id: "org-1",
    agent_role: "ba",
    lesson_type: "code_pattern",
    trigger_context: "When analyzing product specs",
    lesson: "Always extract user personas first",
    evidence: null,
    pipeline_id: null,
    confidence: 0.9,
    times_applied: 5,
    times_reinforced: 2,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-02T00:00:00Z",
  },
  {
    id: "l-2",
    org_id: "org-1",
    agent_role: "ba",
    lesson_type: "style",
    trigger_context: "When writing summaries",
    lesson: "Use bullet points for clarity",
    evidence: null,
    pipeline_id: null,
    confidence: 0.6,
    times_applied: 3,
    times_reinforced: 1,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: null,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockGetLessons.mockResolvedValue(MOCK_LESSONS);
});

describe("LessonsTab", () => {
  it("renders lessons list", async () => {
    render(<LessonsTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Always extract user personas first")).toBeTruthy();
    });

    expect(screen.getByText("Use bullet points for clarity")).toBeTruthy();
    expect(screen.getByText("2 lessons")).toBeTruthy();
  });

  it("delete removes lesson", async () => {
    mockDeleteLesson.mockResolvedValue(undefined);

    render(<LessonsTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Always extract user personas first")).toBeTruthy();
    });

    // Click the first delete button (there are 2 lessons, so 2 trash icons)
    const deleteButtons = screen.getAllByTitle("Delete");
    fireEvent.click(deleteButtons[0]);

    // Confirm
    fireEvent.click(screen.getByText("Confirm"));

    await waitFor(() => {
      expect(mockDeleteLesson).toHaveBeenCalledWith("l-1");
    });
  });

  it("reinforce updates confidence", async () => {
    const reinforced = { ...MOCK_LESSONS[0], confidence: 0.95, times_reinforced: 3 };
    mockReinforceLesson.mockResolvedValue(reinforced);

    render(<LessonsTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Always extract user personas first")).toBeTruthy();
    });

    const reinforceButtons = screen.getAllByTitle("Reinforce");
    fireEvent.click(reinforceButtons[0]);

    await waitFor(() => {
      expect(mockReinforceLesson).toHaveBeenCalledWith("l-1");
    });
  });

  it("edit inline updates lesson", async () => {
    const updated = { ...MOCK_LESSONS[0], lesson: "Updated lesson text" };
    mockUpdateLesson.mockResolvedValue(updated);

    render(<LessonsTab role="ba" />);

    await waitFor(() => {
      expect(screen.getByText("Always extract user personas first")).toBeTruthy();
    });

    // Click edit
    const editButtons = screen.getAllByTitle("Edit");
    fireEvent.click(editButtons[0]);

    // Find textarea and change content
    const textarea = screen.getByDisplayValue("Always extract user personas first");
    fireEvent.change(textarea, { target: { value: "Updated lesson text" } });

    // Save
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockUpdateLesson).toHaveBeenCalledWith("l-1", {
        lesson: "Updated lesson text",
        trigger_context: "When analyzing product specs",
      });
    });
  });
});
