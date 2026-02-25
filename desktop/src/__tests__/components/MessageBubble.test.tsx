import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageBubble } from "@/components/conversation/MessageBubble";
import type { Message } from "@/types/message";

// Mock clipboard API
Object.assign(navigator, {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
});

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "msg-1",
    conversationId: "conv-1",
    author: { type: "agent", role: "engineer", name: "Engineer" },
    content: [{ type: "text", text: "Hello world" }],
    createdAt: "2024-06-15T10:30:00Z",
    ...overrides,
  };
}

describe("MessageBubble", () => {
  // ─── Text rendering ─────────────────────────

  it("renders text content", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders agent name with role color", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByText("Engineer")).toBeInTheDocument();
  });

  it("renders user messages", () => {
    render(
      <MessageBubble
        message={makeMessage({
          author: { type: "user", userId: "u1", name: "Alice" },
          content: [{ type: "text", text: "User message" }],
        })}
      />
    );
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("User message")).toBeInTheDocument();
  });

  it("renders agent emoji avatar", () => {
    render(<MessageBubble message={makeMessage()} />);
    // Engineer emoji is 💻
    expect(screen.getByText("\u{1F4BB}")).toBeInTheDocument();
  });

  // ─── Code blocks ───────────────────────────

  it("renders code blocks with language label", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{ type: "code", language: "typescript", code: "const x = 1;" }],
        })}
      />
    );
    expect(screen.getByText("const x = 1;")).toBeInTheDocument();
    expect(screen.getByText("typescript")).toBeInTheDocument();
  });

  it("renders code blocks with filename", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "code",
            language: "rust",
            code: "fn main() {}",
            filename: "src/main.rs",
          }],
        })}
      />
    );
    expect(screen.getByText("src/main.rs")).toBeInTheDocument();
    expect(screen.getByText("fn main() {}")).toBeInTheDocument();
  });

  it("shows copy button on code blocks", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{ type: "code", language: "js", code: "console.log('hi')" }],
        })}
      />
    );
    expect(screen.getByTitle("Copy code")).toBeInTheDocument();
  });

  it("shows Open in VS Code button when filename provided", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "code",
            language: "ts",
            code: "export {}",
            filename: "src/app.ts",
          }],
        })}
      />
    );
    expect(screen.getByTitle("Open in VS Code")).toBeInTheDocument();
  });

  it("shows line count for code blocks", () => {
    const multiLineCode = "line1\nline2\nline3\nline4\nline5";
    render(
      <MessageBubble
        message={makeMessage({
          content: [{ type: "code", language: "text", code: multiLineCode }],
        })}
      />
    );
    expect(screen.getByText("5 lines")).toBeInTheDocument();
  });

  // ─── Diff viewer ───────────────────────────

  it("renders diff blocks with additions and deletions", () => {
    const diff = "+added line\n-removed line\n unchanged";
    render(
      <MessageBubble
        message={makeMessage({
          content: [{ type: "diff", diff, filename: "src/app.ts" }],
        })}
      />
    );
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("-1")).toBeInTheDocument();
  });

  // ─── Approval cards ────────────────────────

  it("renders approval request cards", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "approval_request",
            stage: "architecture",
            summary: "System design ready for review",
            approvalId: "apr-1",
          }],
        })}
      />
    );
    expect(screen.getByText(/System design ready for review/)).toBeInTheDocument();
  });

  it("renders approval response", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "approval_response",
            approved: true,
            comment: "Looks great",
          }],
        })}
      />
    );
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText(/Looks great/)).toBeInTheDocument();
  });

  it("renders rejection response", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "approval_response",
            approved: false,
            comment: "Needs changes",
          }],
        })}
      />
    );
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });

  // ─── System messages ───────────────────────

  it("renders system pipeline events", () => {
    render(
      <MessageBubble
        message={makeMessage({
          author: { type: "system" },
          content: [{
            type: "pipeline_event",
            event: "step_completed",
            details: { step: "Architecture" },
          }],
        })}
      />
    );
    expect(screen.getByText("step completed")).toBeInTheDocument();
  });

  // ─── File attachments ──────────────────────

  it("renders file attachments with size", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "file_attachment",
            filename: "report.pdf",
            url: "https://example.com/report.pdf",
            size: 1048576,
          }],
        })}
      />
    );
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("1.0 MB")).toBeInTheDocument();
  });

  // ─── Cost updates ─────────────────────────

  it("renders cost updates", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{
            type: "cost_update",
            totalCost: 0.4567,
            breakdown: { architect: 0.3, pm: 0.15 },
          }],
        })}
      />
    );
    expect(screen.getByText("$0.4567")).toBeInTheDocument();
  });

  // ─── Reactions ─────────────────────────────

  it("renders reactions", () => {
    render(
      <MessageBubble
        message={makeMessage({
          reactions: [
            { emoji: "\u{1F44D}", users: ["u1", "u2"] },
            { emoji: "\u2764\uFE0F", users: ["u1"] },
          ],
        })}
      />
    );
    // Check count badges
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  // ─── Grouped messages ─────────────────────

  it("hides author name when grouped", () => {
    render(<MessageBubble message={makeMessage()} grouped />);
    expect(screen.queryByText("Engineer")).not.toBeInTheDocument();
  });

  // ─── Thread actions ───────────────────────

  it("calls onOpenThread when Reply in thread is clicked", () => {
    const onOpenThread = vi.fn();
    const { container } = render(
      <MessageBubble message={makeMessage()} onOpenThread={onOpenThread} />
    );

    // Hover to reveal actions
    fireEvent.mouseEnter(container.firstChild as Element);
    const threadBtn = screen.getByTitle("Reply in thread");
    fireEvent.click(threadBtn);

    expect(onOpenThread).toHaveBeenCalledWith("msg-1");
  });

  // ─── Inline markdown ──────────────────────

  it("renders bold text", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{ type: "text", text: "This is **bold** text" }],
        })}
      />
    );
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });

  it("renders inline code", () => {
    render(
      <MessageBubble
        message={makeMessage({
          content: [{ type: "text", text: "Use `console.log` to debug" }],
        })}
      />
    );
    expect(screen.getByText("console.log").tagName).toBe("CODE");
  });
});
