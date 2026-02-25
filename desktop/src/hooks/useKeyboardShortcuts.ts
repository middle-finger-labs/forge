import { useEffect, useCallback } from "react";
import { useLayoutStore } from "@/stores/layoutStore";
import { useConversationStore } from "@/stores/conversationStore";
import { AGENT_ROLES } from "@/types/agent";

// ─── Shortcut definitions ────────────────────────────

export interface ShortcutDef {
  key: string;
  meta?: boolean;
  shift?: boolean;
  label: string;
  description: string;
  action: () => void;
}

// ─── Hook ────────────────────────────────────────────

export function useKeyboardShortcuts() {
  const {
    quickSwitcherOpen,
    detailPanelOpen,
    threadState,
    newPipelineModalOpen,
    toggleQuickSwitcher,
    toggleDetailPanel,
    closeDetailPanel,
    closeThread,
    openNewPipelineModal,
    closeNewPipelineModal,
    settingsOpen,
    activityFeedOpen,
    openSettings,
    closeSettings,
    openActivityFeed,
    closeActivityFeed,
  } = useLayoutStore();

  const { setActiveConversation } = useConversationStore();

  // Check if an input/textarea is focused
  const isInputFocused = useCallback(() => {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || (el as HTMLElement).isContentEditable;
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;

      // ─── Meta shortcuts (always active) ──────

      // Cmd+K: Quick switcher
      if (meta && e.key === "k") {
        e.preventDefault();
        toggleQuickSwitcher();
        return;
      }

      // Cmd+N: New pipeline
      if (meta && e.key === "n") {
        e.preventDefault();
        openNewPipelineModal();
        return;
      }

      // Cmd+,: Settings
      if (meta && e.key === ",") {
        e.preventDefault();
        if (settingsOpen) {
          closeSettings();
        } else {
          openSettings();
        }
        return;
      }

      // Cmd+Shift+A: Activity feed
      if (meta && e.shiftKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        if (activityFeedOpen) {
          closeActivityFeed();
        } else {
          openActivityFeed();
        }
        return;
      }

      // Cmd+.: Toggle detail panel
      if (meta && e.key === ".") {
        e.preventDefault();
        toggleDetailPanel();
        return;
      }

      // Cmd+1-7: Jump to agent DM
      if (meta && !e.shiftKey && e.key >= "1" && e.key <= "7") {
        e.preventDefault();
        const idx = parseInt(e.key) - 1;
        if (idx < AGENT_ROLES.length) {
          setActiveConversation(`dm-${AGENT_ROLES[idx]}`);
        }
        return;
      }

      // Cmd+Shift+Enter: Send and approve (handled by MessageInput)
      // Cmd+Enter: Send message (handled by MessageInput)

      // ─── Escape cascade ──────────────────────

      if (e.key === "Escape") {
        // Don't intercept if an input is focused and has content
        // (let the input handle its own escape behavior)

        if (activityFeedOpen) {
          closeActivityFeed();
          return;
        }
        if (settingsOpen) {
          closeSettings();
          return;
        }
        if (newPipelineModalOpen) {
          closeNewPipelineModal();
          return;
        }
        if (quickSwitcherOpen) {
          toggleQuickSwitcher();
          return;
        }
        if (threadState) {
          closeThread();
          return;
        }
        if (detailPanelOpen) {
          closeDetailPanel();
          return;
        }
        return;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    quickSwitcherOpen,
    detailPanelOpen,
    threadState,
    newPipelineModalOpen,
    settingsOpen,
    activityFeedOpen,
    toggleQuickSwitcher,
    toggleDetailPanel,
    closeDetailPanel,
    closeThread,
    openNewPipelineModal,
    closeNewPipelineModal,
    openSettings,
    closeSettings,
    openActivityFeed,
    closeActivityFeed,
    setActiveConversation,
    isInputFocused,
  ]);
}

// ─── Shortcut reference (for help display) ───────────

export const SHORTCUT_MAP: { key: string; label: string }[] = [
  { key: "\u2318,", label: "Settings" },
  { key: "\u2318\u21E7A", label: "Activity feed" },
  { key: "\u2318K", label: "Quick switcher" },
  { key: "\u2318N", label: "New pipeline" },
  { key: "\u2318.", label: "Toggle detail panel" },
  { key: "\u2318\u21E7F", label: "Focus Forge (global)" },
  { key: "\u23181-7", label: "Jump to agent" },
  { key: "\u2318\u23CE", label: "Send message" },
  { key: "Esc", label: "Close panel/modal" },
];
