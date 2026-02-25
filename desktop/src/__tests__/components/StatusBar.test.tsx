import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBar } from "@/components/layout/StatusBar";
import { useConnectionStore } from "@/stores/connectionStore";
import type { PipelineRun } from "@/types/pipeline";

function resetStores() {
  useConnectionStore.setState({
    serverUrl: "http://forge.test:8000",
    connectionStatus: "authenticated",
    connectionError: null,
    authToken: "token",
    user: { id: "u1", email: "a@b.com", name: "Alice", role: "admin", createdAt: "" },
    org: { id: "o1", name: "Acme Inc", slug: "acme", plan: "pro", memberCount: 3 },
    rememberMe: true,
  });
}

const makePipelineRun = (overrides: Partial<PipelineRun> = {}): PipelineRun => ({
  id: "p1",
  name: "Test Pipeline",
  status: "running",
  steps: [],
  startedAt: "2024-01-01T00:00:00Z",
  cost: { total: 1.23, perAgent: {} },
  ...overrides,
});

describe("StatusBar", () => {
  beforeEach(resetStores);

  it("shows connection status when authenticated", () => {
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText(/Connected to forge.test:8000/)).toBeInTheDocument();
  });

  it("shows 'No active pipelines' when none running", () => {
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText("No active pipelines")).toBeInTheDocument();
  });

  it("shows active pipeline count", () => {
    const runs = [
      makePipelineRun({ id: "p1", status: "running" }),
      makePipelineRun({ id: "p2", status: "running" }),
      makePipelineRun({ id: "p3", status: "completed" }),
    ];
    render(<StatusBar pipelineRuns={runs} />);
    expect(screen.getByText("2 pipelines running")).toBeInTheDocument();
  });

  it("shows singular 'pipeline' for 1 active", () => {
    render(<StatusBar pipelineRuns={[makePipelineRun()]} />);
    expect(screen.getByText("1 pipeline running")).toBeInTheDocument();
  });

  it("shows total cost", () => {
    const runs = [
      makePipelineRun({ cost: { total: 1.50, perAgent: {} } }),
      makePipelineRun({ id: "p2", cost: { total: 0.75, perAgent: {} } }),
    ];
    render(<StatusBar pipelineRuns={runs} />);
    expect(screen.getByText("$2.25 today")).toBeInTheDocument();
  });

  it("hides cost when zero", () => {
    render(<StatusBar pipelineRuns={[makePipelineRun({ cost: { total: 0, perAgent: {} } })]} />);
    expect(screen.queryByText(/today/)).not.toBeInTheDocument();
  });

  it("shows user name", () => {
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });

  it("shows org name", () => {
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText("Acme Inc")).toBeInTheDocument();
  });

  it("shows connecting state", () => {
    useConnectionStore.setState({ connectionStatus: "connecting" });
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText(/Connecting/)).toBeInTheDocument();
  });

  it("shows error state", () => {
    useConnectionStore.setState({ connectionStatus: "error" });
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText("Connection error")).toBeInTheDocument();
  });

  it("shows disconnected state", () => {
    useConnectionStore.setState({ connectionStatus: "disconnected" });
    render(<StatusBar pipelineRuns={[]} />);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });
});
