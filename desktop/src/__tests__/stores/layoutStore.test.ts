import { describe, it, expect, beforeEach } from "vitest";
import { useLayoutStore } from "@/stores/layoutStore";

function resetStore() {
  useLayoutStore.setState({
    detailPanelOpen: false,
    detailPanelContent: null,
    sidebarWidth: 240,
    quickSwitcherOpen: false,
    threadState: null,
    newPipelineModalOpen: false,
    settingsOpen: false,
    activityFeedOpen: false,
  });
}

describe("layoutStore", () => {
  beforeEach(resetStore);

  // ─── Detail panel ───────────────────────────────

  describe("detail panel", () => {
    it("toggleDetailPanel opens with default 'dag' content", () => {
      useLayoutStore.getState().toggleDetailPanel();
      const state = useLayoutStore.getState();
      expect(state.detailPanelOpen).toBe(true);
      expect(state.detailPanelContent).toBe("dag");
    });

    it("toggleDetailPanel closes and clears content", () => {
      useLayoutStore.getState().openDetailPanel("files");
      useLayoutStore.getState().toggleDetailPanel();
      const state = useLayoutStore.getState();
      expect(state.detailPanelOpen).toBe(false);
      expect(state.detailPanelContent).toBeNull();
    });

    it("openDetailPanel sets specific content", () => {
      useLayoutStore.getState().openDetailPanel("agent-profile");
      expect(useLayoutStore.getState().detailPanelContent).toBe("agent-profile");
      expect(useLayoutStore.getState().detailPanelOpen).toBe(true);
    });

    it("closeDetailPanel resets everything", () => {
      useLayoutStore.getState().openDetailPanel("files");
      useLayoutStore.getState().closeDetailPanel();
      const state = useLayoutStore.getState();
      expect(state.detailPanelOpen).toBe(false);
      expect(state.detailPanelContent).toBeNull();
      expect(state.threadState).toBeNull();
    });
  });

  // ─── Sidebar width ─────────────────────────────

  describe("sidebar width", () => {
    it("setSidebarWidth clamps to range [180, 400]", () => {
      useLayoutStore.getState().setSidebarWidth(100);
      expect(useLayoutStore.getState().sidebarWidth).toBe(180);

      useLayoutStore.getState().setSidebarWidth(500);
      expect(useLayoutStore.getState().sidebarWidth).toBe(400);

      useLayoutStore.getState().setSidebarWidth(300);
      expect(useLayoutStore.getState().sidebarWidth).toBe(300);
    });
  });

  // ─── Quick Switcher ─────────────────────────────

  describe("quick switcher", () => {
    it("toggleQuickSwitcher opens and closes", () => {
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(false);

      useLayoutStore.getState().toggleQuickSwitcher();
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(true);

      useLayoutStore.getState().toggleQuickSwitcher();
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(false);
    });

    it("closeQuickSwitcher explicitly closes", () => {
      useLayoutStore.setState({ quickSwitcherOpen: true });
      useLayoutStore.getState().closeQuickSwitcher();
      expect(useLayoutStore.getState().quickSwitcherOpen).toBe(false);
    });
  });

  // ─── Thread ────────────────────────────────────

  describe("thread", () => {
    it("openThread opens detail panel with thread content", () => {
      useLayoutStore.getState().openThread("msg-1", "conv-1");
      const state = useLayoutStore.getState();
      expect(state.detailPanelOpen).toBe(true);
      expect(state.detailPanelContent).toBe("thread");
      expect(state.threadState).toEqual({ messageId: "msg-1", conversationId: "conv-1" });
    });

    it("closeThread closes detail panel and clears thread", () => {
      useLayoutStore.getState().openThread("msg-1", "conv-1");
      useLayoutStore.getState().closeThread();
      const state = useLayoutStore.getState();
      expect(state.detailPanelOpen).toBe(false);
      expect(state.threadState).toBeNull();
    });

    it("switching to non-thread content clears threadState", () => {
      useLayoutStore.getState().openThread("msg-1", "conv-1");
      useLayoutStore.getState().openDetailPanel("dag");
      expect(useLayoutStore.getState().threadState).toBeNull();
    });
  });

  // ─── New Pipeline Modal ────────────────────────

  describe("new pipeline modal", () => {
    it("opens and closes", () => {
      useLayoutStore.getState().openNewPipelineModal();
      expect(useLayoutStore.getState().newPipelineModalOpen).toBe(true);

      useLayoutStore.getState().closeNewPipelineModal();
      expect(useLayoutStore.getState().newPipelineModalOpen).toBe(false);
    });
  });

  // ─── Settings / Activity Feed mutual exclusion ─

  describe("settings and activity feed", () => {
    it("openSettings closes activity feed", () => {
      useLayoutStore.setState({ activityFeedOpen: true });
      useLayoutStore.getState().openSettings();
      expect(useLayoutStore.getState().settingsOpen).toBe(true);
      expect(useLayoutStore.getState().activityFeedOpen).toBe(false);
    });

    it("openActivityFeed closes settings", () => {
      useLayoutStore.setState({ settingsOpen: true });
      useLayoutStore.getState().openActivityFeed();
      expect(useLayoutStore.getState().activityFeedOpen).toBe(true);
      expect(useLayoutStore.getState().settingsOpen).toBe(false);
    });

    it("closeSettings only closes settings", () => {
      useLayoutStore.setState({ settingsOpen: true, activityFeedOpen: false });
      useLayoutStore.getState().closeSettings();
      expect(useLayoutStore.getState().settingsOpen).toBe(false);
    });

    it("closeActivityFeed only closes activity feed", () => {
      useLayoutStore.setState({ activityFeedOpen: true, settingsOpen: false });
      useLayoutStore.getState().closeActivityFeed();
      expect(useLayoutStore.getState().activityFeedOpen).toBe(false);
    });
  });
});
