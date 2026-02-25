import { useEffect, useCallback, useRef } from "react";
import { Sidebar } from "./Sidebar";
import { Toolbar } from "./Toolbar";
import { MainPanel } from "./MainPanel";
import { DetailPanel } from "./DetailPanel";
import { StatusBar } from "./StatusBar";
import { QuickSwitcher } from "./QuickSwitcher";
import { MobileShell } from "./MobileShell";
import { ThreadView } from "@/components/conversation/ThreadView";
import { NewPipelineModal } from "@/components/pipeline/NewPipelineModal";
import { IndexRepoModal } from "@/components/codebase/IndexRepoModal";
import { SettingsWindow } from "@/components/settings/SettingsWindow";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { OnboardingView } from "@/components/onboarding/OnboardingView";
import { OnboardingBanner } from "@/components/onboarding/OnboardingBanner";
import { useOnboarding } from "@/hooks/useOnboarding";
import { useLayoutStore } from "@/stores/layoutStore";
import { useOnboardingStore } from "@/stores/onboardingStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useRepoStore } from "@/stores/repoStore";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useNotifications } from "@/hooks/useNotifications";
import { useResponsiveLayout } from "@/hooks/useResponsiveLayout";
import {
  MOCK_AGENTS,
  MOCK_CONVERSATIONS,
  MOCK_PIPELINE_RUNS,
  MOCK_MESSAGES,
  MOCK_REPOS,
} from "@/data/mockData";

export function AppShell() {
  const { mode } = useResponsiveLayout();

  if (mode === "mobile") {
    return <MobileShell />;
  }

  return <DesktopShell />;
}

function DesktopShell() {
  const {
    sidebarWidth,
    detailPanelOpen,
    detailPanelContent,
    quickSwitcherOpen,
    threadState,
    newPipelineModalOpen,
    settingsOpen,
    activityFeedOpen,
    setSidebarWidth,
    closeThread,
    closeNewPipelineModal,
    closeSettings,
    closeActivityFeed,
  } = useLayoutStore();

  const { showOnboarding, showBanner } = useOnboarding();
  const { resumeOnboarding } = useOnboardingStore();

  const handleResumeBanner = useCallback(() => {
    resumeOnboarding();
  }, [resumeOnboarding]);

  const {
    setConversations,
    setAgents,
    setMessages,
    setActiveConversation,
    addConversation,
  } = useConversationStore();

  const { setRepos } = useRepoStore();

  // Register all keyboard shortcuts
  useKeyboardShortcuts();

  // Initialize notifications (requests permission on mount)
  useNotifications();

  // Seed mock data on mount
  useEffect(() => {
    setConversations(MOCK_CONVERSATIONS);
    setAgents(MOCK_AGENTS);
    setRepos(MOCK_REPOS);
    for (const [convId, msgs] of Object.entries(MOCK_MESSAGES)) {
      setMessages(convId, msgs);
    }
  }, [setConversations, setAgents, setMessages, setRepos]);

  // Sidebar resize
  const resizing = useRef(false);
  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      resizing.current = true;
      const onMove = (ev: MouseEvent) => {
        if (resizing.current) {
          setSidebarWidth(ev.clientX);
        }
      };
      const onUp = () => {
        resizing.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [setSidebarWidth]
  );

  const showThread = detailPanelOpen && detailPanelContent === "thread" && threadState;

  return (
    <>
      <div
        className="app-shell"
        style={{
          "--sidebar-width": `${sidebarWidth}px`,
          "--detail-width": detailPanelOpen ? "320px" : "0px",
        } as React.CSSProperties}
      >
        <div className="app-shell__sidebar">
          <Sidebar pipelineRuns={MOCK_PIPELINE_RUNS} />
        </div>

        <div className="app-shell__resize" onMouseDown={onResizeStart} />

        <div className="app-shell__toolbar">
          <Toolbar pipelineRuns={MOCK_PIPELINE_RUNS} />
        </div>

        <div className="app-shell__main">
          {showBanner && !settingsOpen && !activityFeedOpen && !showOnboarding && (
            <OnboardingBanner onResume={handleResumeBanner} />
          )}
          {settingsOpen ? (
            <SettingsWindow onClose={closeSettings} />
          ) : activityFeedOpen ? (
            <ActivityFeed onClose={closeActivityFeed} />
          ) : showOnboarding ? (
            <OnboardingView />
          ) : (
            <MainPanel pipelineRuns={MOCK_PIPELINE_RUNS} />
          )}
        </div>

        {detailPanelOpen && (
          <div className="app-shell__detail">
            {showThread ? (
              <ThreadView
                parentMessageId={threadState.messageId}
                conversationId={threadState.conversationId}
                onClose={closeThread}
              />
            ) : (
              <DetailPanel pipelineRuns={MOCK_PIPELINE_RUNS} />
            )}
          </div>
        )}

        <div className="app-shell__statusbar">
          <StatusBar pipelineRuns={MOCK_PIPELINE_RUNS} />
        </div>
      </div>

      {quickSwitcherOpen && <QuickSwitcher />}

      <IndexRepoModal />

      {newPipelineModalOpen && (
        <NewPipelineModal
          onClose={closeNewPipelineModal}
          onCreate={(spec, options) => {
            const pipelineId = `run-${Date.now()}`;
            const convId = `pipeline-${pipelineId}`;
            const now = new Date().toISOString();

            addConversation({
              id: convId,
              type: "pipeline",
              title: spec.slice(0, 40) + (spec.length > 40 ? "..." : ""),
              pipelineId,
              participants: [
                { type: "user", id: "me", name: "You" },
              ],
              createdAt: now,
              updatedAt: now,
              unreadCount: 0,
            });

            setMessages(convId, [
              {
                id: `msg-${Date.now()}`,
                conversationId: convId,
                author: { type: "system" },
                content: [
                  {
                    type: "pipeline_event",
                    event: "pipeline_started",
                    details: { spec, ...options },
                  },
                ],
                createdAt: now,
              },
            ]);

            setActiveConversation(convId);
            closeNewPipelineModal();
          }}
        />
      )}
    </>
  );
}
