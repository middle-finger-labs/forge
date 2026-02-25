import {
  useState,
  useRef,
  useCallback,
  useEffect,
  type KeyboardEvent,
  type DragEvent,
} from "react";
import { AGENT_REGISTRY, AGENT_ROLES } from "@/types/agent";
import type { AgentRole } from "@/types/agent";
import type { MessageContent } from "@/types/message";
import { useResponsiveLayout } from "@/hooks/useResponsiveLayout";
import { useHaptics } from "@/hooks/useHaptics";
import { useOfflineStore } from "@/stores/offlineStore";
import { useRepoStore } from "@/stores/repoStore";
import { Paperclip, Send, Slash, Plus, WifiOff, FolderGit2, X } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Slash commands ─────────────────────────────────────

interface SlashCommand {
  name: string;
  description: string;
  prefix: string;
}

const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "pipeline",
    description: "Create a new pipeline from your message",
    prefix: "/pipeline",
  },
  {
    name: "new",
    description: "Create a new pipeline (alias)",
    prefix: "/new",
  },
  {
    name: "approve",
    description: "Approve the current pending stage",
    prefix: "/approve",
  },
  {
    name: "reject",
    description: "Reject with a comment",
    prefix: "/reject",
  },
  {
    name: "status",
    description: "Show all pipeline statuses",
    prefix: "/status",
  },
  {
    name: "cost",
    description: "Show cost summary",
    prefix: "/cost",
  },
];

// ─── Props ──────────────────────────────────────────────

interface MessageInputProps {
  /** Conversation title for placeholder */
  conversationTitle: string;
  /** Called when user sends a message */
  onSend: (content: MessageContent[]) => void;
  /** Called when a slash command is invoked */
  onSlashCommand?: (command: string, args: string) => void;
  /** Whether the input is disabled */
  disabled?: boolean;
  /** Custom placeholder text */
  placeholder?: string;
  /** Typing indicator: who is currently typing */
  typingUsers?: string[];
  /** Called when the user starts/stops typing */
  onTyping?: (isTyping: boolean) => void;
}

// ─── MessageInput ───────────────────────────────────────

export function MessageInput({
  conversationTitle,
  onSend,
  onSlashCommand,
  disabled = false,
  placeholder: customPlaceholder,
  typingUsers = [],
  onTyping,
}: MessageInputProps) {
  const { isMobile } = useResponsiveLayout();
  const { haptic } = useHaptics();
  const [text, setText] = useState("");
  const [showSlash, setShowSlash] = useState(false);
  const [showMentions, setShowMentions] = useState(false);
  const [showRepoSelector, setShowRepoSelector] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const [mentionFilter, setMentionFilter] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isTypingRef = useRef(false);

  // Repo context
  const { repos, activeRepoId, setActiveRepo, clearActiveRepo } = useRepoStore();
  const activeRepo = activeRepoId ? repos[activeRepoId] : undefined;

  // Max textarea height: 4 lines on mobile (~96px), 200px on desktop
  const maxTextareaHeight = isMobile ? 96 : 200;

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxTextareaHeight)}px`;
  }, [text, maxTextareaHeight]);

  // Typing indicator debounce
  const emitTyping = useCallback(
    (typing: boolean) => {
      if (!onTyping) return;
      if (typing && !isTypingRef.current) {
        isTypingRef.current = true;
        onTyping(true);
      }

      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current);
      }

      if (typing) {
        typingTimeoutRef.current = setTimeout(() => {
          isTypingRef.current = false;
          onTyping(false);
        }, 3000);
      } else {
        isTypingRef.current = false;
        onTyping(false);
      }
    },
    [onTyping]
  );

  // Filtered slash commands
  const filteredCommands = SLASH_COMMANDS.filter(
    (cmd) =>
      !slashFilter ||
      cmd.name.startsWith(slashFilter) ||
      cmd.prefix.startsWith(`/${slashFilter}`)
  );

  // Filtered agents for @mentions
  const filteredAgents = AGENT_ROLES.filter(
    (role) =>
      !mentionFilter ||
      role.includes(mentionFilter.toLowerCase()) ||
      AGENT_REGISTRY[role].displayName
        .toLowerCase()
        .includes(mentionFilter.toLowerCase())
  );

  // Handle text change
  const handleChange = useCallback(
    (value: string) => {
      setText(value);
      emitTyping(value.length > 0);

      // Slash commands only on desktop
      if (!isMobile && value.startsWith("/")) {
        const cmd = value.slice(1).split(" ")[0];
        setSlashFilter(cmd);
        setShowSlash(true);
        setShowMentions(false);
        setSelectedIdx(0);
      } else {
        setShowSlash(false);
      }

      // Detect @mention mode
      const lastAt = value.lastIndexOf("@");
      if (lastAt >= 0 && !value.slice(lastAt).includes(" ")) {
        const query = value.slice(lastAt + 1);
        setMentionFilter(query);
        setShowMentions(true);
        setShowSlash(false);
        setSelectedIdx(0);
      } else {
        setShowMentions(false);
      }
    },
    [emitTyping, isMobile]
  );

  // Send message
  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;

    haptic("medium");

    // Check for slash command (desktop only)
    if (!isMobile && trimmed.startsWith("/")) {
      const parts = trimmed.split(" ");
      const cmd = parts[0].slice(1);
      const args = parts.slice(1).join(" ");
      onSlashCommand?.(cmd, args);
      setText("");
      setShowSlash(false);
      emitTyping(false);
      return;
    }

    // Check for @mention pattern: @role message
    const mentionMatch = trimmed.match(/^@(\w+)\s+(.+)/s);
    if (mentionMatch) {
      const role = mentionMatch[1] as AgentRole;
      if (AGENT_ROLES.includes(role)) {
        const content: MessageContent[] = [
          { type: "text", text: trimmed },
        ];
        onSend(content);
        setText("");
        emitTyping(false);
        return;
      }
    }

    // Regular message
    const content: MessageContent[] = [{ type: "text", text: trimmed }];
    onSend(content);
    setText("");
    emitTyping(false);
  }, [text, disabled, onSend, onSlashCommand, emitTyping, isMobile, haptic]);

  // Keyboard handling
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Slash command or mention selection
      if (showSlash || showMentions) {
        const list = showSlash ? filteredCommands : filteredAgents;
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSelectedIdx((i) => Math.min(i + 1, list.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSelectedIdx((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
          e.preventDefault();
          if (showSlash && filteredCommands[selectedIdx]) {
            setText(filteredCommands[selectedIdx].prefix + " ");
            setShowSlash(false);
          } else if (showMentions && filteredAgents[selectedIdx]) {
            const role = filteredAgents[selectedIdx];
            const lastAt = text.lastIndexOf("@");
            setText(text.slice(0, lastAt) + `@${role} `);
            setShowMentions(false);
          }
          return;
        }
        if (e.key === "Escape") {
          setShowSlash(false);
          setShowMentions(false);
          return;
        }
      }

      // Enter to send (shift+enter for newline) — desktop only
      // On mobile, Enter creates a newline; the send button handles sending
      if (!isMobile && e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [
      showSlash,
      showMentions,
      filteredCommands,
      filteredAgents,
      selectedIdx,
      text,
      handleSend,
      isMobile,
    ]
  );

  // File drop handling
  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);

      const files = Array.from(e.dataTransfer.files);
      if (files.length === 0) return;

      // Create file attachment content blocks
      const attachments: MessageContent[] = files.map((file) => ({
        type: "file_attachment" as const,
        filename: file.name,
        url: URL.createObjectURL(file),
        size: file.size,
      }));

      // If there's text, include it too
      const content: MessageContent[] = [];
      if (text.trim()) {
        content.push({ type: "text", text: text.trim() });
      }
      content.push(...attachments);

      onSend(content);
      setText("");
    },
    [text, onSend]
  );

  // ── Mobile layout ──
  const { networkStatus } = useOfflineStore();
  const isOffline = isMobile && networkStatus === "offline";
  const offlinePlaceholder = "Message will be sent when online";

  if (isMobile) {
    return (
      <div className="px-3 pb-[env(safe-area-inset-bottom)] pt-2 shrink-0 border-t border-[var(--forge-border)]">
        {/* Typing indicator */}
        {typingUsers.length > 0 && (
          <div className="flex items-center gap-1.5 mb-1.5 px-1">
            <TypingDots />
            <span className="text-xs text-[var(--forge-text-muted)]">
              {formatTypingUsers(typingUsers)}
            </span>
          </div>
        )}

        {/* Offline hint */}
        {isOffline && text.trim() && (
          <div className="flex items-center gap-1 mb-1.5 px-1 text-[10px] text-[var(--forge-warning)]">
            <WifiOff className="w-3 h-3" />
            <span>Message will be queued and sent when you reconnect</span>
          </div>
        )}

        {/* @mention popup — positioned above input */}
        {showMentions && filteredAgents.length > 0 && (
          <MobileMentionPopup
            agents={filteredAgents}
            onSelect={(role) => {
              const lastAt = text.lastIndexOf("@");
              setText(text.slice(0, lastAt) + `@${role} `);
              setShowMentions(false);
              textareaRef.current?.focus();
            }}
          />
        )}

        {/* Input area */}
        <div className={cn(
          "flex items-end gap-2 rounded-2xl border bg-[var(--forge-bg)] px-3 py-2 transition-colors",
          isOffline
            ? "border-[var(--forge-warning)]/30 focus-within:border-[var(--forge-warning)]"
            : "border-[var(--forge-border)] focus-within:border-[var(--forge-accent)]",
        )}>
          {/* Attachment / plus button */}
          <button
            aria-label="Attach file"
            className="p-1 rounded-full text-[var(--forge-text-muted)] active:bg-[var(--forge-hover)] shrink-0 mb-0.5"
          >
            <Plus className="w-5 h-5" />
          </button>

          {/* Textarea — capped at 4 lines */}
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={isOffline ? offlinePlaceholder : (customPlaceholder ?? "Message...")}
            rows={1}
            className={cn(
              "flex-1 bg-transparent text-sm text-[var(--forge-text)] resize-none outline-none",
              "placeholder:text-[var(--forge-text-muted)]",
              "min-h-[24px] py-0.5"
            )}
            style={{ maxHeight: `${maxTextareaHeight}px` }}
          />

          {/* Send button — prominent on mobile */}
          <button
            onClick={handleSend}
            disabled={disabled || !text.trim()}
            aria-label="Send message"
            className={cn(
              "p-2 rounded-full transition-colors shrink-0 mb-0.5",
              text.trim()
                ? "bg-[var(--forge-accent)] text-white active:opacity-80"
                : "text-[var(--forge-text-muted)]"
            )}
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  // ── Desktop layout (existing) ──
  const readyRepos = Object.values(repos).filter((r) => r.indexingStatus === "ready");

  return (
    <div className="px-4 pb-4 pt-2 shrink-0">
      {/* Typing indicator */}
      {typingUsers.length > 0 && (
        <div className="flex items-center gap-1.5 mb-1.5 px-1">
          <TypingDots />
          <span className="text-xs text-[var(--forge-text-muted)]">
            {formatTypingUsers(typingUsers)}
          </span>
        </div>
      )}

      {/* Repo context chip */}
      {activeRepo && (
        <div className="flex items-center gap-2 mb-1.5 px-1">
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--forge-accent)]/10 border border-[var(--forge-accent)]/20 text-xs">
            <FolderGit2 className="w-3 h-3 text-[var(--forge-accent)]" />
            <span className="text-[var(--forge-accent)] font-medium">{activeRepo.name}</span>
            {activeRepo.lastIndexedAt && (
              <span className="text-[var(--forge-text-muted)]">
                (indexed {formatRepoAge(activeRepo.lastIndexedAt)})
              </span>
            )}
            <button
              onClick={clearActiveRepo}
              className="p-0.5 rounded-full hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
              title="Remove repo context"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}

      {/* Slash command / mention popup */}
      {showSlash && filteredCommands.length > 0 && (
        <CommandPopup
          commands={filteredCommands}
          selectedIdx={selectedIdx}
          onSelect={(cmd) => {
            setText(cmd.prefix + " ");
            setShowSlash(false);
            textareaRef.current?.focus();
          }}
        />
      )}

      {showMentions && filteredAgents.length > 0 && (
        <MentionPopup
          agents={filteredAgents}
          selectedIdx={selectedIdx}
          onSelect={(role) => {
            const lastAt = text.lastIndexOf("@");
            setText(text.slice(0, lastAt) + `@${role} `);
            setShowMentions(false);
            textareaRef.current?.focus();
          }}
        />
      )}

      {/* Repo selector popup */}
      {showRepoSelector && readyRepos.length > 0 && (
        <RepoSelectorPopup
          repos={readyRepos}
          activeRepoId={activeRepoId}
          onSelect={(repoId) => {
            setActiveRepo(repoId);
            setShowRepoSelector(false);
            textareaRef.current?.focus();
          }}
          onClose={() => setShowRepoSelector(false)}
        />
      )}

      {/* Input area */}
      <div
        className={cn(
          "relative rounded-lg border bg-[var(--forge-bg)] transition-colors",
          dragOver
            ? "border-[var(--forge-accent)] bg-[var(--forge-accent)]/5"
            : "border-[var(--forge-border)] focus-within:border-[var(--forge-accent)]"
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {dragOver && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--forge-accent)]/10 rounded-lg z-10 pointer-events-none">
            <span className="text-sm text-[var(--forge-accent)] font-medium">
              Drop files to attach
            </span>
          </div>
        )}

        <div className="flex items-end gap-2 px-3 py-2">
          {/* Attachment button */}
          <button
            className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors shrink-0 mb-0.5"
            title="Attach file"
          >
            <Paperclip className="w-4 h-4" />
          </button>

          {/* Repo context button */}
          <button
            onClick={() => setShowRepoSelector(!showRepoSelector)}
            className={cn(
              "p-1 rounded transition-colors shrink-0 mb-0.5",
              activeRepoId
                ? "text-[var(--forge-accent)] hover:bg-[var(--forge-accent)]/10"
                : "text-[var(--forge-text-muted)] hover:bg-[var(--forge-hover)] hover:text-white"
            )}
            title={activeRepo ? `Context: ${activeRepo.name}` : "Select repo context"}
          >
            <FolderGit2 className="w-4 h-4" />
          </button>

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={
              customPlaceholder ??
              (activeRepo
                ? `Ask about ${activeRepo.name}...`
                : `Message ${conversationTitle}...`)
            }
            rows={1}
            className={cn(
              "flex-1 bg-transparent text-sm text-[var(--forge-text)] resize-none outline-none",
              "placeholder:text-[var(--forge-text-muted)]",
              "min-h-[24px] max-h-[200px] py-0.5"
            )}
          />

          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={disabled || !text.trim()}
            className={cn(
              "p-1.5 rounded transition-colors shrink-0 mb-0.5",
              text.trim()
                ? "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)]"
                : "text-[var(--forge-text-muted)] cursor-not-allowed"
            )}
            title="Send message"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Hints */}
      <div className="flex justify-between items-center mt-1 px-1">
        <div className="flex items-center gap-3 text-[10px] text-[var(--forge-text-muted)]">
          <span>
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">
              Enter
            </kbd>{" "}
            send
          </span>
          <span>
            <kbd className="font-mono bg-[var(--forge-hover)] px-1 rounded">
              Shift+Enter
            </kbd>{" "}
            newline
          </span>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-[var(--forge-text-muted)]">
          <Slash className="w-3 h-3" />
          <span>commands</span>
        </div>
      </div>
    </div>
  );
}

// ─── Command popup ──────────────────────────────────────

function CommandPopup({
  commands,
  selectedIdx,
  onSelect,
}: {
  commands: SlashCommand[];
  selectedIdx: number;
  onSelect: (cmd: SlashCommand) => void;
}) {
  return (
    <div className="mb-1 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl overflow-hidden">
      <div className="px-3 py-1.5 border-b border-[var(--forge-border)]">
        <span className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          Commands
        </span>
      </div>
      {commands.map((cmd, i) => (
        <button
          key={cmd.name}
          onClick={() => onSelect(cmd)}
          className={cn(
            "w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors text-left",
            i === selectedIdx
              ? "bg-[var(--forge-accent)]/10 text-white"
              : "hover:bg-[var(--forge-hover)] text-[var(--forge-text)]"
          )}
        >
          <code className="text-xs font-mono text-[var(--forge-accent)] bg-[var(--forge-accent)]/10 px-1.5 py-0.5 rounded">
            {cmd.prefix}
          </code>
          <span className="text-xs text-[var(--forge-text-muted)]">
            {cmd.description}
          </span>
        </button>
      ))}
    </div>
  );
}

// ─── Mention popup ──────────────────────────────────────

function MentionPopup({
  agents,
  selectedIdx,
  onSelect,
}: {
  agents: AgentRole[];
  selectedIdx: number;
  onSelect: (role: AgentRole) => void;
}) {
  return (
    <div className="mb-1 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl overflow-hidden">
      <div className="px-3 py-1.5 border-b border-[var(--forge-border)]">
        <span className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          Mention an agent
        </span>
      </div>
      {agents.map((role, i) => {
        const info = AGENT_REGISTRY[role];
        return (
          <button
            key={role}
            onClick={() => onSelect(role)}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors text-left",
              i === selectedIdx
                ? "bg-[var(--forge-accent)]/10 text-white"
                : "hover:bg-[var(--forge-hover)] text-[var(--forge-text)]"
            )}
          >
            <span className="text-base">{info.emoji}</span>
            <span className="font-medium">{info.displayName}</span>
            <span className="text-xs text-[var(--forge-text-muted)]">
              @{role}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ─── Mobile mention popup (above keyboard) ──────────────

function MobileMentionPopup({
  agents,
  onSelect,
}: {
  agents: AgentRole[];
  onSelect: (role: AgentRole) => void;
}) {
  return (
    <div className="mb-2 rounded-xl border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl overflow-hidden max-h-52 overflow-y-auto">
      <div className="px-3 py-2 border-b border-[var(--forge-border)] sticky top-0 bg-[var(--forge-bg)]">
        <span className="text-[11px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          Mention an agent
        </span>
      </div>
      {agents.map((role) => {
        const info = AGENT_REGISTRY[role];
        return (
          <button
            key={role}
            onClick={() => onSelect(role)}
            className="w-full flex items-center gap-3 px-3 py-3 text-sm text-left active:bg-[var(--forge-hover)] transition-colors"
          >
            <span className="text-lg">{info.emoji}</span>
            <div className="min-w-0 flex-1">
              <span className="font-medium text-white">{info.displayName}</span>
              <span className="text-xs text-[var(--forge-text-muted)] ml-2">@{role}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── Typing dots animation ──────────────────────────────

function TypingDots() {
  return (
    <span className="inline-flex gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-[var(--forge-text-muted)]"
          style={{
            animation: "typing-bounce 1.4s ease-in-out infinite",
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
    </span>
  );
}

// ─── Repo selector popup ─────────────────────────────────

function RepoSelectorPopup({
  repos,
  activeRepoId,
  onSelect,
  onClose,
}: {
  repos: Array<{ id: string; name: string; chunkCount: number; languages: string[]; lastIndexedAt?: string }>;
  activeRepoId: string | null;
  onSelect: (repoId: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="mb-1 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] shadow-xl overflow-hidden">
      <div className="px-3 py-1.5 border-b border-[var(--forge-border)] flex items-center justify-between">
        <span className="text-[10px] font-medium text-[var(--forge-text-muted)] uppercase tracking-wider">
          Select repo context
        </span>
        {activeRepoId && (
          <button
            onClick={() => {
              onClose();
            }}
            className="text-[10px] text-[var(--forge-text-muted)] hover:text-white transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
      {repos.map((repo) => (
        <button
          key={repo.id}
          onClick={() => onSelect(repo.id)}
          className={cn(
            "w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors text-left",
            repo.id === activeRepoId
              ? "bg-[var(--forge-accent)]/10 text-white"
              : "hover:bg-[var(--forge-hover)] text-[var(--forge-text)]"
          )}
        >
          <FolderGit2 className="w-4 h-4 text-[var(--forge-text-muted)] shrink-0" />
          <div className="min-w-0 flex-1">
            <span className="font-medium">{repo.name}</span>
            <span className="text-[10px] text-[var(--forge-text-muted)] ml-2">
              {repo.chunkCount} chunks · {repo.languages.slice(0, 2).join(", ")}
            </span>
          </div>
          {repo.id === activeRepoId && (
            <span className="text-[10px] text-[var(--forge-accent)] shrink-0">Active</span>
          )}
        </button>
      ))}
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────

function formatRepoAge(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatTypingUsers(users: string[]): string {
  if (users.length === 1) return `${users[0]} is typing...`;
  if (users.length === 2) return `${users[0]} and ${users[1]} are typing...`;
  return `${users[0]} and ${users.length - 1} others are typing...`;
}
