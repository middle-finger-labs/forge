import { useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { AGENT_REGISTRY } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import type { Message, MessageContent } from "@/types/message";
import { ApprovalCard } from "@/components/pipeline/ApprovalCard";
import { PipelineSummaryCard } from "@/components/pipeline/PipelineSummaryCard";
import { MobileApprovalCard } from "@/components/conversation/MobileApprovalCard";
import { MobileCodeViewer } from "@/components/conversation/MobileCodeViewer";
import { MobileDiffViewer } from "@/components/conversation/MobileDiffViewer";
import { useResponsiveLayout } from "@/hooks/useResponsiveLayout";
import {
  Zap,
  File,
  FileDown,
  Copy,
  MessageSquare,
  SmilePlus,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Check,
  CircleDot,
  CircleCheck,
  CircleX,
  CirclePlay,
  DollarSign,
  Terminal,
  Maximize2,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Agent role colors ──────────────────────────────────

const AGENT_COLORS: Record<AgentRole, string> = {
  ba: "bg-blue-500/10 border-blue-500/20",
  researcher: "bg-purple-500/10 border-purple-500/20",
  architect: "bg-amber-500/10 border-amber-500/20",
  pm: "bg-green-500/10 border-green-500/20",
  engineer: "bg-cyan-500/10 border-cyan-500/20",
  qa: "bg-pink-500/10 border-pink-500/20",
  cto: "bg-red-500/10 border-red-500/20",
};

const AGENT_NAME_COLORS: Record<AgentRole, string> = {
  ba: "text-blue-400",
  researcher: "text-purple-400",
  architect: "text-amber-400",
  pm: "text-green-400",
  engineer: "text-cyan-400",
  qa: "text-pink-400",
  cto: "text-red-400",
};

// ─── Props ──────────────────────────────────────────────

interface MessageBubbleProps {
  message: Message;
  /** Whether this message is grouped with the previous (same author within 5 min) */
  grouped?: boolean;
  /** Callback to open a thread */
  onOpenThread?: (messageId: string) => void;
}

// ─── MessageBubble ──────────────────────────────────────

export function MessageBubble({
  message,
  grouped = false,
  onOpenThread,
}: MessageBubbleProps) {
  const { author, content, createdAt } = message;
  const [hovered, setHovered] = useState(false);
  const { isMobile } = useResponsiveLayout();

  const isSystem = author.type === "system";
  const isAgent = author.type === "agent";
  const isUser = author.type === "user";

  // System messages: centered divider style
  if (isSystem) {
    return (
      <div className="py-1">
        {content.map((block, i) => (
          <SystemContentBlock key={i} block={block} />
        ))}
      </div>
    );
  }

  const authorName =
    author.type === "agent" ? author.name : author.type === "user" ? author.name : "";
  const authorEmoji =
    author.type === "agent" ? AGENT_REGISTRY[author.role]?.emoji : undefined;
  const agentRole = author.type === "agent" ? author.role : undefined;

  // ── Mobile layout: top-aligned name (Slack/iMessage style), full-width ──
  if (isMobile) {
    return (
      <div
        className={cn(
          "px-3 w-full",
          !grouped && "mt-3 first:mt-0",
          grouped && "mt-0.5"
        )}
      >
        {/* Avatar + author line — only for non-grouped */}
        {!grouped && (
          <div className="flex items-center gap-2 mb-1">
            {isAgent && authorEmoji ? (
              <div
                className={cn(
                  "w-7 h-7 rounded-md flex items-center justify-center text-sm border",
                  agentRole && AGENT_COLORS[agentRole]
                )}
              >
                {authorEmoji}
              </div>
            ) : (
              <div className="w-7 h-7 rounded-md bg-[var(--forge-accent)] flex items-center justify-center text-white text-xs font-bold">
                {authorName.charAt(0).toUpperCase()}
              </div>
            )}
            <span
              className={cn(
                "font-semibold text-[13px]",
                agentRole ? AGENT_NAME_COLORS[agentRole] : "text-white"
              )}
            >
              {authorName}
            </span>
            <span className="text-[10px] text-[var(--forge-text-muted)]">
              {formatTime(createdAt)}
            </span>
          </div>
        )}

        {/* Content blocks — full width, no alignment */}
        <div className={cn("space-y-2", !grouped && "pl-9")}>
          {content.map((block, i) => (
            <MobileContentBlock key={i} block={block} />
          ))}
        </div>

        {/* Reactions */}
        {message.reactions && message.reactions.length > 0 && (
          <div className={cn("flex flex-wrap gap-1 mt-1", !grouped && "pl-9")}>
            {message.reactions.map((r, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[var(--forge-hover)] text-xs"
              >
                {r.emoji}{" "}
                <span className="text-[var(--forge-text-muted)]">
                  {r.users.length}
                </span>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── Desktop layout (existing) ──
  return (
    <div
      className={cn(
        "group relative px-5 -mx-5 rounded",
        hovered && "bg-white/[0.02]",
        !grouped && "mt-4 first:mt-0",
        grouped && "mt-0.5"
      )}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div
        className={cn(
          "flex gap-3",
          isUser && "flex-row-reverse"
        )}
      >
        {/* Avatar — only shown for non-grouped messages */}
        <div className="shrink-0 w-9 mt-0.5">
          {!grouped ? (
            isAgent && authorEmoji ? (
              <div
                className={cn(
                  "w-9 h-9 rounded-lg flex items-center justify-center text-lg border",
                  agentRole && AGENT_COLORS[agentRole]
                )}
              >
                {authorEmoji}
              </div>
            ) : (
              <div className="w-9 h-9 rounded-lg bg-[var(--forge-accent)] flex items-center justify-center text-white text-sm font-bold">
                {authorName.charAt(0).toUpperCase()}
              </div>
            )
          ) : (
            // Grouped: show timestamp on hover
            <div className="w-9 h-9 flex items-center justify-center">
              {hovered && (
                <span className="text-[10px] text-[var(--forge-text-muted)]">
                  {formatTime(createdAt)}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Content */}
        <div className={cn("min-w-0 flex-1", isUser && "text-right")}>
          {/* Author line — only for non-grouped */}
          {!grouped && (
            <div
              className={cn(
                "flex items-baseline gap-2 mb-0.5",
                isUser && "flex-row-reverse"
              )}
            >
              <span
                className={cn(
                  "font-semibold text-sm",
                  agentRole ? AGENT_NAME_COLORS[agentRole] : "text-white"
                )}
              >
                {authorName}
              </span>
              <span className="text-[10px] text-[var(--forge-text-muted)]">
                {formatTime(createdAt)}
              </span>
            </div>
          )}

          {/* Content blocks */}
          <div className={cn("space-y-2", isUser && "flex flex-col items-end")}>
            {content.map((block, i) => (
              <ContentBlock key={i} block={block} />
            ))}
          </div>

          {/* Reactions (if any) */}
          {message.reactions && message.reactions.length > 0 && (
            <div className="flex gap-1 mt-1">
              {message.reactions.map((r, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[var(--forge-hover)] text-xs cursor-pointer hover:bg-[var(--forge-border)] transition-colors"
                >
                  {r.emoji}{" "}
                  <span className="text-[var(--forge-text-muted)]">
                    {r.users.length}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Hover actions */}
      {hovered && (
        <HoverActions
          messageId={message.id}
          content={content}
          onOpenThread={onOpenThread}
          isUser={isUser}
        />
      )}
    </div>
  );
}

// ─── Hover actions toolbar ──────────────────────────────

function HoverActions({
  messageId,
  content,
  onOpenThread,
  isUser,
}: {
  messageId: string;
  content: MessageContent[];
  onOpenThread?: (id: string) => void;
  isUser: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const text = content
      .map((block) => {
        switch (block.type) {
          case "text":
            return block.text;
          case "markdown":
            return block.markdown;
          case "code":
            return block.code;
          case "diff":
            return block.diff;
          default:
            return "";
        }
      })
      .filter(Boolean)
      .join("\n\n");

    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [content]);

  return (
    <div
      className={cn(
        "absolute -top-3 flex items-center gap-0.5 rounded-md border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-lg px-1 py-0.5 z-10",
        isUser ? "left-14" : "right-4"
      )}
    >
      {onOpenThread && (
        <ActionButton
          icon={<MessageSquare className="w-3.5 h-3.5" />}
          title="Reply in thread"
          onClick={() => onOpenThread(messageId)}
        />
      )}
      <ActionButton
        icon={<SmilePlus className="w-3.5 h-3.5" />}
        title="Add reaction"
        onClick={() => {}}
      />
      <ActionButton
        icon={
          copied ? (
            <Check className="w-3.5 h-3.5 text-[var(--forge-success)]" />
          ) : (
            <Copy className="w-3.5 h-3.5" />
          )
        }
        title="Copy text"
        onClick={handleCopy}
      />
      <ActionButton
        icon={<ExternalLink className="w-3.5 h-3.5" />}
        title="Open in detail panel"
        onClick={() => {}}
      />
    </div>
  );
}

function ActionButton({
  icon,
  title,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="p-1.5 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
    >
      {icon}
    </button>
  );
}

// ─── System content (centered divider) ──────────────────

function SystemContentBlock({ block }: { block: MessageContent }) {
  if (block.type === "pipeline_event") {
    const icon = PIPELINE_EVENT_ICONS[block.event] ?? (
      <CircleDot className="w-3 h-3" />
    );
    return (
      <div className="flex items-center gap-2 text-xs text-[var(--forge-text-muted)] py-1">
        <div className="flex-1 h-px bg-[var(--forge-border)]" />
        <span className="flex items-center gap-1.5 shrink-0">
          {icon}
          {block.event.replace(/_/g, " ")}
          {"step" in block.details && block.details.step != null && (
            <span className="text-[var(--forge-text)]">
              {String(block.details.step)}
            </span>
          )}
        </span>
        <div className="flex-1 h-px bg-[var(--forge-border)]" />
      </div>
    );
  }

  // Fallback for other system content
  return (
    <div className="flex items-center gap-2 text-xs text-[var(--forge-text-muted)] py-1 justify-center">
      <ContentBlock block={block} />
    </div>
  );
}

const PIPELINE_EVENT_ICONS: Record<string, React.ReactNode> = {
  step_started: <CirclePlay className="w-3 h-3 text-[var(--forge-accent)]" />,
  step_completed: (
    <CircleCheck className="w-3 h-3 text-[var(--forge-success)]" />
  ),
  step_failed: <CircleX className="w-3 h-3 text-[var(--forge-error)]" />,
  pipeline_completed: (
    <CircleCheck className="w-3 h-3 text-[var(--forge-success)]" />
  ),
  pipeline_failed: <CircleX className="w-3 h-3 text-[var(--forge-error)]" />,
  approval_needed: <Zap className="w-3 h-3 text-[var(--forge-warning)]" />,
};

// ─── Content blocks ─────────────────────────────────────

function ContentBlock({ block }: { block: MessageContent }) {
  switch (block.type) {
    case "text":
      return <TextBlock text={block.text} />;
    case "markdown":
      return <MarkdownBlock markdown={block.markdown} />;
    case "code":
      return (
        <CodeBlock
          code={block.code}
          language={block.language}
          filename={block.filename}
        />
      );
    case "diff":
      return <DiffBlock diff={block.diff} filename={block.filename} />;
    case "approval_request":
      return (
        <ApprovalCard
          stage={block.stage}
          summary={block.summary}
          approvalId={block.approvalId}
          pending={true}
          onApprove={(comment) => {
            // Will be wired to backend
            console.log("Approved", block.approvalId, comment);
          }}
          onRequestChanges={(comment) => {
            // Will be wired to backend
            console.log("Changes requested", block.approvalId, comment);
          }}
        />
      );
    case "approval_response":
      return (
        <ApprovalResponseBlock
          approved={block.approved}
          comment={block.comment}
        />
      );
    case "file_attachment":
      return (
        <FileAttachmentBlock
          filename={block.filename}
          url={block.url}
          size={block.size}
        />
      );
    case "pipeline_event":
      return (
        <div className="flex items-center gap-2 text-xs text-[var(--forge-text-muted)] py-1">
          <div className="flex-1 h-px bg-[var(--forge-border)]" />
          <span>{block.event.replace(/_/g, " ")}</span>
          <div className="flex-1 h-px bg-[var(--forge-border)]" />
        </div>
      );
    case "cost_update":
      return (
        <CostUpdateBlock
          totalCost={block.totalCost}
          breakdown={block.breakdown}
        />
      );
    case "pipeline_summary":
      return <PipelineSummaryCard data={block} />;
    case "code_reference":
      return <CodeReferenceBlock block={block} />;
  }
}

// ─── Mobile content blocks ──────────────────────────────────

function MobileContentBlock({ block }: { block: MessageContent }) {
  switch (block.type) {
    case "text":
      return <TextBlock text={block.text} />;
    case "markdown":
      return <MarkdownBlock markdown={block.markdown} />;
    case "code":
      return (
        <MobileCodeBlock
          code={block.code}
          language={block.language}
          filename={block.filename}
        />
      );
    case "diff":
      return <MobileDiffBlock diff={block.diff} filename={block.filename} />;
    case "approval_request":
      return (
        <MobileApprovalCard
          stage={block.stage}
          summary={block.summary}
          approvalId={block.approvalId}
          pending={true}
          onApprove={(comment) => {
            console.log("Approved", block.approvalId, comment);
          }}
          onRequestChanges={(comment) => {
            console.log("Changes requested", block.approvalId, comment);
          }}
        />
      );
    case "approval_response":
      return (
        <ApprovalResponseBlock
          approved={block.approved}
          comment={block.comment}
        />
      );
    case "file_attachment":
      return (
        <FileAttachmentBlock
          filename={block.filename}
          url={block.url}
          size={block.size}
        />
      );
    case "pipeline_event":
      return (
        <div className="flex items-center gap-2 text-xs text-[var(--forge-text-muted)] py-1">
          <div className="flex-1 h-px bg-[var(--forge-border)]" />
          <span>{block.event.replace(/_/g, " ")}</span>
          <div className="flex-1 h-px bg-[var(--forge-border)]" />
        </div>
      );
    case "cost_update":
      return (
        <CostUpdateBlock
          totalCost={block.totalCost}
          breakdown={block.breakdown}
        />
      );
    case "pipeline_summary":
      return <PipelineSummaryCard data={block} />;
    case "code_reference":
      return <CodeReferenceBlock block={block} />;
  }
}

// ─── Mobile code block (compact with "View full" button) ────

function MobileCodeBlock({
  code,
  language,
  filename,
}: {
  code: string;
  language: string;
  filename?: string;
}) {
  const [showFullScreen, setShowFullScreen] = useState(false);
  const lineCount = code.split("\n").length;
  const previewLines = code.split("\n").slice(0, 6).join("\n");
  const isTruncated = lineCount > 6;

  return (
    <>
      <div className="rounded-lg border border-[var(--forge-border)] overflow-hidden w-full">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--forge-bg)] border-b border-[var(--forge-border)]">
          <span className="text-xs text-[var(--forge-text-muted)] truncate">
            {filename ?? language}
          </span>
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-[var(--forge-text-muted)]">
              {lineCount} lines
            </span>
            <button
              onClick={() => setShowFullScreen(true)}
              className="p-1 rounded text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)]"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Preview — horizontal scroll, capped at 6 lines */}
        <pre className="p-3 bg-[var(--forge-bg)] overflow-x-auto">
          <code className="text-xs text-[var(--forge-text)] font-mono leading-5">
            {previewLines}
          </code>
        </pre>

        {/* "View full" button */}
        {isTruncated && (
          <button
            onClick={() => setShowFullScreen(true)}
            className="w-full py-2 text-center text-xs text-[var(--forge-accent)] bg-[var(--forge-bg)] border-t border-[var(--forge-border)] active:bg-[var(--forge-hover)]"
          >
            View full ({lineCount} lines)
          </button>
        )}
      </div>

      {/* Full-screen viewer */}
      {showFullScreen && (
        <MobileCodeViewer
          code={code}
          language={language}
          filename={filename}
          onClose={() => setShowFullScreen(false)}
        />
      )}
    </>
  );
}

// ─── Mobile diff block (collapsed by default, tap to expand) ─

function MobileDiffBlock({ diff, filename }: { diff: string; filename: string }) {
  const [showFullScreen, setShowFullScreen] = useState(false);
  const lines = diff.split("\n");
  const additions = lines.filter((l) => l.startsWith("+")).length;
  const deletions = lines.filter((l) => l.startsWith("-")).length;

  return (
    <>
      <button
        onClick={() => setShowFullScreen(true)}
        className="w-full rounded-lg border border-[var(--forge-border)] overflow-hidden text-left active:bg-[var(--forge-hover)]"
      >
        <div className="flex items-center justify-between px-3 py-2.5 bg-[var(--forge-bg)]">
          <span className="text-xs text-[var(--forge-text-muted)] truncate flex-1">
            {filename}
          </span>
          <div className="flex items-center gap-2 text-[11px] shrink-0 ml-2">
            {additions > 0 && (
              <span className="text-[var(--forge-success)]">+{additions}</span>
            )}
            {deletions > 0 && (
              <span className="text-[var(--forge-error)]">-{deletions}</span>
            )}
            <Maximize2 className="w-3.5 h-3.5 text-[var(--forge-text-muted)]" />
          </div>
        </div>
      </button>

      {/* Full-screen diff viewer */}
      {showFullScreen && (
        <MobileDiffViewer
          diff={diff}
          filename={filename}
          onClose={() => setShowFullScreen(false)}
        />
      )}
    </>
  );
}

// ─── Text block (basic inline markdown) ─────────────────

function TextBlock({ text }: { text: string }) {
  return (
    <p className="text-sm text-[var(--forge-text)] whitespace-pre-wrap break-words">
      {renderInlineMarkdown(text)}
    </p>
  );
}

/** Very lightweight inline markdown: **bold**, *italic*, `code`, [links](url) */
function renderInlineMarkdown(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const regex =
    /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|\[(.+?)\]\((.+?)\))/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    // Text before this match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (match[2]) {
      // **bold**
      parts.push(
        <strong key={match.index} className="font-semibold text-white">
          {match[2]}
        </strong>
      );
    } else if (match[3]) {
      // *italic*
      parts.push(
        <em key={match.index} className="italic">
          {match[3]}
        </em>
      );
    } else if (match[4]) {
      // `code`
      parts.push(
        <code
          key={match.index}
          className="px-1.5 py-0.5 rounded bg-[var(--forge-bg)] text-[var(--forge-accent)] text-xs font-mono"
        >
          {match[4]}
        </code>
      );
    } else if (match[5] && match[6]) {
      // [link](url)
      parts.push(
        <a
          key={match.index}
          href={match[6]}
          className="text-[var(--forge-accent)] hover:underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          {match[5]}
        </a>
      );
    }

    lastIndex = match.index + match[0].length;
  }

  // Remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

// ─── Markdown block (full rendering) ────────────────────

function MarkdownBlock({ markdown }: { markdown: string }) {
  // Split into paragraphs and render headings, lists, code blocks, etc.
  return (
    <div className="text-sm text-[var(--forge-text)] space-y-2 break-words">
      {markdown.split("\n\n").map((paragraph, i) => {
        const trimmed = paragraph.trim();

        // Heading
        const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)/);
        if (headingMatch) {
          const level = headingMatch[1].length;
          const text = headingMatch[2];
          const Tag = `h${level + 1}` as "h2" | "h3" | "h4";
          return (
            <Tag
              key={i}
              className={cn(
                "font-semibold text-white",
                level === 1 && "text-base",
                level === 2 && "text-sm",
                level === 3 && "text-sm"
              )}
            >
              {renderInlineMarkdown(text)}
            </Tag>
          );
        }

        // Bullet list
        if (trimmed.match(/^[-*]\s/m)) {
          const items = trimmed.split("\n").filter((l) => l.match(/^[-*]\s/));
          return (
            <ul key={i} className="list-disc list-inside space-y-0.5">
              {items.map((item, j) => (
                <li key={j} className="text-[var(--forge-text)]">
                  {renderInlineMarkdown(item.replace(/^[-*]\s+/, ""))}
                </li>
              ))}
            </ul>
          );
        }

        // Fenced code block
        if (trimmed.startsWith("```")) {
          const lines = trimmed.split("\n");
          const lang = lines[0].replace("```", "").trim();
          const code = lines.slice(1, -1).join("\n");
          return (
            <CodeBlock key={i} code={code} language={lang || "text"} />
          );
        }

        // Regular paragraph
        return (
          <p key={i} className="whitespace-pre-wrap">
            {renderInlineMarkdown(trimmed)}
          </p>
        );
      })}
    </div>
  );
}

// ─── Code block ─────────────────────────────────────────

function CodeBlock({
  code,
  language,
  filename,
}: {
  code: string;
  language: string;
  filename?: string;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [copied, setCopied] = useState(false);
  const lineCount = code.split("\n").length;

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  return (
    <div className="rounded-lg border border-[var(--forge-border)] overflow-hidden max-w-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--forge-bg)] border-b border-[var(--forge-border)]">
        <div className="flex items-center gap-2 min-w-0">
          {lineCount > 10 && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="text-[var(--forge-text-muted)] hover:text-white transition-colors"
            >
              {collapsed ? (
                <ChevronRight className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
          )}
          <span className="text-xs text-[var(--forge-text-muted)] truncate">
            {filename ?? language}
          </span>
          {filename && (
            <span className="text-[10px] text-[var(--forge-text-muted)] uppercase shrink-0">
              {language}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <span className="text-[10px] text-[var(--forge-text-muted)] mr-1">
            {lineCount} lines
          </span>
          {filename && (
            <button
              onClick={() => {
                invoke("open_in_vscode", { path: filename }).catch((e) =>
                  console.error("Failed to open in VS Code:", e)
                );
              }}
              className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-[var(--forge-accent)] transition-colors"
              title="Open in VS Code"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
          )}
          {filename && (
            <button
              onClick={() => {
                // Open the directory containing the file
                const dir = filename.includes("/")
                  ? filename.substring(0, filename.lastIndexOf("/"))
                  : ".";
                invoke("open_in_terminal", { path: dir }).catch((e) =>
                  console.error("Failed to open terminal:", e)
                );
              }}
              className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
              title="Open in Terminal"
            >
              <Terminal className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={handleCopy}
            className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
            title="Copy code"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-[var(--forge-success)]" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Code content */}
      {!collapsed && (
        <pre className="p-3 bg-[var(--forge-bg)] overflow-x-auto">
          <code className="text-xs text-[var(--forge-text)] font-mono leading-5">
            {code}
          </code>
        </pre>
      )}
    </div>
  );
}

// ─── Diff block ─────────────────────────────────────────

function DiffBlock({ diff, filename }: { diff: string; filename: string }) {
  const [collapsed, setCollapsed] = useState(false);
  const lines = diff.split("\n");
  const additions = lines.filter((l) => l.startsWith("+")).length;
  const deletions = lines.filter((l) => l.startsWith("-")).length;

  return (
    <div className="rounded-lg border border-[var(--forge-border)] overflow-hidden max-w-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--forge-bg)] border-b border-[var(--forge-border)]">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="text-[var(--forge-text-muted)] hover:text-white transition-colors"
          >
            {collapsed ? (
              <ChevronRight className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
          <span className="text-xs text-[var(--forge-text-muted)]">
            {filename}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          {additions > 0 && (
            <span className="text-[var(--forge-success)]">+{additions}</span>
          )}
          {deletions > 0 && (
            <span className="text-[var(--forge-error)]">-{deletions}</span>
          )}
        </div>
      </div>

      {/* Diff content */}
      {!collapsed && (
        <pre className="p-3 bg-[var(--forge-bg)] overflow-x-auto">
          <code className="text-xs font-mono leading-5">
            {lines.map((line, i) => (
              <span
                key={i}
                className={cn(
                  "block",
                  line.startsWith("+") &&
                    "text-[var(--forge-success)] bg-[var(--forge-success)]/5",
                  line.startsWith("-") &&
                    "text-[var(--forge-error)] bg-[var(--forge-error)]/5",
                  !line.startsWith("+") &&
                    !line.startsWith("-") &&
                    "text-[var(--forge-text-muted)]"
                )}
              >
                {line}
              </span>
            ))}
          </code>
        </pre>
      )}
    </div>
  );
}


// ─── Code reference block ────────────────────────────────

function CodeReferenceBlock({
  block,
}: {
  block: Extract<MessageContent, { type: "code_reference" }>;
}) {
  const lineRange = block.endLine
    ? `L${block.startLine}-${block.endLine}`
    : `L${block.startLine}`;

  return (
    <div className="rounded-lg border border-[var(--forge-border)] overflow-hidden max-w-full">
      {/* Header with file path and "Open in VS Code" */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--forge-bg)] border-b border-[var(--forge-border)]">
        <div className="flex items-center gap-2 min-w-0">
          <File className="w-3.5 h-3.5 text-[var(--forge-text-muted)] shrink-0" />
          <span className="text-xs text-[var(--forge-accent)] truncate font-mono">
            {block.filePath}
          </span>
          <span className="text-[10px] text-[var(--forge-text-muted)] shrink-0">
            {lineRange}
          </span>
          {block.language && (
            <span className="text-[10px] text-[var(--forge-text-muted)] uppercase shrink-0">
              {block.language}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <span className="text-[10px] text-[var(--forge-text-muted)] mr-1">
            {block.repoName}
          </span>
          <button
            onClick={() => {
              invoke("open_in_vscode", {
                path: block.filePath,
                line: block.startLine,
              }).catch((e) =>
                console.error("Failed to open in VS Code:", e)
              );
            }}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--forge-accent)]/10 text-[var(--forge-accent)] hover:bg-[var(--forge-accent)]/20 transition-colors"
            title={`Open ${block.filePath}:${block.startLine} in VS Code`}
          >
            <ExternalLink className="w-3 h-3" />
            Open in VS Code
          </button>
        </div>
      </div>

      {/* Code snippet */}
      {block.snippet && (
        <pre className="p-3 bg-[var(--forge-bg)] overflow-x-auto">
          <code className="text-xs text-[var(--forge-text)] font-mono leading-5">
            {block.snippet.split("\n").map((line, i) => (
              <span key={i} className="block">
                <span className="inline-block w-8 text-right mr-3 text-[var(--forge-text-muted)] select-none">
                  {block.startLine + i}
                </span>
                {line}
              </span>
            ))}
          </code>
        </pre>
      )}
    </div>
  );
}

// ─── Approval response ──────────────────────────────────

function ApprovalResponseBlock({
  approved,
  comment,
}: {
  approved: boolean;
  comment?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm",
        approved
          ? "bg-[var(--forge-success)]/10 text-[var(--forge-success)] border border-[var(--forge-success)]/20"
          : "bg-[var(--forge-error)]/10 text-[var(--forge-error)] border border-[var(--forge-error)]/20"
      )}
    >
      <span>{approved ? "\u2705" : "\u274C"}</span>
      <span className="font-medium">
        {approved ? "Approved" : "Rejected"}
      </span>
      {comment && (
        <span className="text-[var(--forge-text-muted)]">— {comment}</span>
      )}
    </div>
  );
}

// ─── File attachment ────────────────────────────────────

function FileAttachmentBlock({
  filename,
  url: _url,
  size,
}: {
  filename: string;
  url: string;
  size: number;
}) {
  return (
    <button className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] text-sm hover:bg-[var(--forge-hover)] transition-colors cursor-pointer">
      <FileDown className="w-4 h-4 text-[var(--forge-accent)]" />
      <span className="text-[var(--forge-text)]">{filename}</span>
      <span className="text-[10px] text-[var(--forge-text-muted)]">
        {formatBytes(size)}
      </span>
    </button>
  );
}

// ─── Cost update ────────────────────────────────────────

function CostUpdateBlock({
  totalCost,
  breakdown,
}: {
  totalCost: number;
  breakdown: Record<string, number>;
}) {
  const entries = Object.entries(breakdown);

  return (
    <div className="inline-flex items-center gap-3 px-3 py-2 rounded-lg bg-[var(--forge-bg)] border border-[var(--forge-border)] text-xs">
      <DollarSign className="w-3.5 h-3.5 text-[var(--forge-text-muted)]" />
      <span className="text-white font-mono font-medium">
        ${totalCost.toFixed(4)}
      </span>
      {entries.length > 0 && (
        <span className="text-[var(--forge-text-muted)]">
          ({entries.map(([k, v]) => `${k}: $${v.toFixed(3)}`).join(", ")})
        </span>
      )}
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
