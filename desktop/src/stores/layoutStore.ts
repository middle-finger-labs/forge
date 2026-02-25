import { create } from "zustand";

export type DetailPanelContent =
  | "dag"
  | "files"
  | "agent-profile"
  | "settings"
  | "thread"
  | "codebase"
  | "activity"
  | null;

interface ThreadState {
  messageId: string;
  conversationId: string;
}

interface LayoutState {
  detailPanelOpen: boolean;
  detailPanelContent: DetailPanelContent;
  sidebarWidth: number;
  quickSwitcherOpen: boolean;
  threadState: ThreadState | null;
  newPipelineModalOpen: boolean;
  settingsOpen: boolean;
  activityFeedOpen: boolean;
  indexRepoModalOpen: boolean;

  toggleDetailPanel: () => void;
  openDetailPanel: (content: DetailPanelContent) => void;
  closeDetailPanel: () => void;
  setSidebarWidth: (width: number) => void;
  toggleQuickSwitcher: () => void;
  closeQuickSwitcher: () => void;
  openThread: (messageId: string, conversationId: string) => void;
  closeThread: () => void;
  openNewPipelineModal: () => void;
  closeNewPipelineModal: () => void;
  openSettings: () => void;
  closeSettings: () => void;
  openActivityFeed: () => void;
  closeActivityFeed: () => void;
  openIndexRepoModal: () => void;
  closeIndexRepoModal: () => void;
}

const MIN_SIDEBAR_WIDTH = 180;
const MAX_SIDEBAR_WIDTH = 400;

export const useLayoutStore = create<LayoutState>((set) => ({
  detailPanelOpen: false,
  detailPanelContent: null,
  sidebarWidth: 240,
  quickSwitcherOpen: false,
  threadState: null,
  newPipelineModalOpen: false,
  settingsOpen: false,
  activityFeedOpen: false,
  indexRepoModalOpen: false,

  toggleDetailPanel: () =>
    set((s) => ({
      detailPanelOpen: !s.detailPanelOpen,
      detailPanelContent: s.detailPanelOpen ? null : s.detailPanelContent ?? "dag",
      // Close thread if closing the panel
      threadState: s.detailPanelOpen ? null : s.threadState,
    })),

  openDetailPanel: (content) =>
    set({
      detailPanelOpen: true,
      detailPanelContent: content,
      // Clear thread if switching to non-thread content
      ...(content !== "thread" ? { threadState: null } : {}),
    }),

  closeDetailPanel: () =>
    set({ detailPanelOpen: false, detailPanelContent: null, threadState: null }),

  setSidebarWidth: (width) =>
    set({
      sidebarWidth: Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width)),
    }),

  toggleQuickSwitcher: () =>
    set((s) => ({ quickSwitcherOpen: !s.quickSwitcherOpen })),

  closeQuickSwitcher: () =>
    set({ quickSwitcherOpen: false }),

  openThread: (messageId, conversationId) =>
    set({
      detailPanelOpen: true,
      detailPanelContent: "thread",
      threadState: { messageId, conversationId },
    }),

  closeThread: () =>
    set({
      detailPanelContent: null,
      detailPanelOpen: false,
      threadState: null,
    }),

  openNewPipelineModal: () => set({ newPipelineModalOpen: true }),
  closeNewPipelineModal: () => set({ newPipelineModalOpen: false }),

  openSettings: () => set({ settingsOpen: true, activityFeedOpen: false }),
  closeSettings: () => set({ settingsOpen: false }),

  openActivityFeed: () => set({ activityFeedOpen: true, settingsOpen: false }),
  closeActivityFeed: () => set({ activityFeedOpen: false }),

  openIndexRepoModal: () => set({ indexRepoModalOpen: true }),
  closeIndexRepoModal: () => set({ indexRepoModalOpen: false }),
}));
