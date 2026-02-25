import { useState, useCallback, useEffect, useMemo } from "react";
import { MobileConversationList } from "./MobileConversationList";
import { MobileConversationView } from "./MobileConversationView";
import { MobilePipelineList } from "./MobilePipelineList";
import { MobileConnectionBar } from "./MobileConnectionBar";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { MobileSettings } from "./MobileSettings";
import { MobileNewPipeline } from "@/components/pipeline/MobileNewPipeline";
import { MobileApprovalQueue } from "@/components/pipeline/MobileApprovalQueue";
import { MobileBottomSheet } from "./MobileBottomSheet";
import { useConversationStore } from "@/stores/conversationStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useNotifications } from "@/hooks/useNotifications";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useHaptics } from "@/hooks/useHaptics";
import { useEdgeSwipeBack } from "@/hooks/useMobileGestures";
import {
  MOCK_AGENTS,
  MOCK_CONVERSATIONS,
  MOCK_PIPELINE_RUNS,
  MOCK_MESSAGES,
} from "@/data/mockData";
import {
  MessageSquare,
  Zap,
  Bell,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────

type MobileTab = "messages" | "pipelines" | "activity" | "settings";
type ActivitySubView = "feed" | "approvals";

interface MobileScreen {
  type: "conversation";
  conversationId: string;
}

// ─── MobileShell ────────────────────────────────────

export function MobileShell() {
  const [activeTab, setActiveTab] = useState<MobileTab>("messages");
  const [screen, setScreen] = useState<MobileScreen | null>(null);
  const [bottomSheetContent, setBottomSheetContent] = useState<"dag" | "profile" | null>(null);
  const [activitySubView, setActivitySubView] = useState<ActivitySubView>("approvals");

  const {
    setConversations,
    setAgents,
    setMessages,
    setActiveConversation,
    conversations,
    messages: allMessages,
    addConversation,
  } = useConversationStore();

  const {
    newPipelineModalOpen,
    closeNewPipelineModal,
  } = useLayoutStore();

  const { haptic } = useHaptics();

  // Register keyboard shortcuts (subset work on mobile)
  useKeyboardShortcuts();
  useNotifications();
  useOfflineSync();

  // Seed mock data
  useEffect(() => {
    setConversations(MOCK_CONVERSATIONS);
    setAgents(MOCK_AGENTS);
    for (const [convId, msgs] of Object.entries(MOCK_MESSAGES)) {
      setMessages(convId, msgs);
    }
  }, [setConversations, setAgents, setMessages]);

  // Navigate into a conversation
  const openConversation = useCallback(
    (conversationId: string) => {
      setActiveConversation(conversationId);
      setScreen({ type: "conversation", conversationId });
    },
    [setActiveConversation]
  );

  // Navigate back from conversation
  const goBack = useCallback(() => {
    setScreen(null);
    setBottomSheetContent(null);
  }, []);

  // Edge swipe back (iOS-style)
  useEdgeSwipeBack(goBack);

  // Android back button handling
  useEffect(() => {
    const handleBackButton = async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const win = getCurrentWindow();
        const unlisten = await win.listen("tauri://back-button", () => {
          if (screen) {
            goBack();
          }
        });
        return unlisten;
      } catch {
        // Not available on non-Tauri platforms
        return undefined;
      }
    };
    let cleanup: (() => void) | undefined;
    handleBackButton().then((unlisten) => { cleanup = unlisten; });
    return () => { cleanup?.(); };
  }, [screen, goBack]);

  // Bottom sheet handlers
  const openDAG = useCallback(() => setBottomSheetContent("dag"), []);
  const openProfile = useCallback(() => setBottomSheetContent("profile"), []);
  const closeBottomSheet = useCallback(() => setBottomSheetContent(null), []);

  // Unread counts for tab badges
  const totalUnread = Object.values(conversations).reduce(
    (sum, c) => sum + c.unreadCount,
    0
  );
  const pipelineUnread = Object.values(conversations)
    .filter((c) => c.type === "pipeline")
    .reduce((sum, c) => sum + c.unreadCount, 0);

  // Count pending approvals across all pipelines
  const approvalCount = useMemo(() => {
    let count = 0;
    for (const conv of Object.values(conversations)) {
      if (conv.type !== "pipeline") continue;
      const msgs = allMessages[conv.id] ?? [];
      for (const msg of msgs) {
        for (const block of msg.content) {
          if (block.type === "approval_request") {
            const hasResponse = msgs.some(
              (m) =>
                m.createdAt > msg.createdAt &&
                m.content.some((c) => c.type === "approval_response"),
            );
            if (!hasResponse) count++;
          }
        }
      }
    }
    return count;
  }, [conversations, allMessages]);

  // If a screen is pushed, render it full-screen above tabs
  if (screen) {
    return (
      <div className="flex flex-col h-[100dvh] bg-[var(--forge-bg)]">
        <MobileConnectionBar />
        <div className="flex-1 min-h-0 relative">
          <MobileConversationView
            conversationId={screen.conversationId}
            pipelineRuns={MOCK_PIPELINE_RUNS}
            onBack={goBack}
            onOpenDAG={openDAG}
            onOpenProfile={openProfile}
          />
          {bottomSheetContent && (
            <MobileBottomSheet
              type={bottomSheetContent}
              conversationId={screen.conversationId}
              pipelineRuns={MOCK_PIPELINE_RUNS}
              onClose={closeBottomSheet}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[100dvh] bg-[var(--forge-bg)]">
      {/* Connection status bar */}
      <MobileConnectionBar />

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === "messages" && (
          <MobileConversationList
            onSelectConversation={openConversation}
            pipelineRuns={MOCK_PIPELINE_RUNS}
          />
        )}
        {activeTab === "pipelines" && (
          <MobilePipelineList
            pipelineRuns={MOCK_PIPELINE_RUNS}
            onSelectPipeline={openConversation}
          />
        )}
        {activeTab === "activity" && (
          <div className="flex flex-col h-full">
            {/* Sub-view toggle */}
            <div className="flex items-center gap-1 px-4 pt-[env(safe-area-inset-top)] shrink-0">
              <div className="flex items-center gap-1 pt-3 pb-2">
                <button
                  onClick={() => setActivitySubView("approvals")}
                  className={cn(
                    "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                    activitySubView === "approvals"
                      ? "bg-[var(--forge-accent)] text-white"
                      : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)]",
                  )}
                >
                  Approvals
                  {approvalCount > 0 && (
                    <span className="ml-1 px-1 py-px rounded-full bg-white/20 text-[10px]">
                      {approvalCount}
                    </span>
                  )}
                </button>
                <button
                  onClick={() => setActivitySubView("feed")}
                  className={cn(
                    "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                    activitySubView === "feed"
                      ? "bg-[var(--forge-accent)] text-white"
                      : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)]",
                  )}
                >
                  Feed
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              {activitySubView === "approvals" ? (
                <MobileApprovalQueue
                  pipelineRuns={MOCK_PIPELINE_RUNS}
                  onNavigateToConversation={openConversation}
                />
              ) : (
                <ActivityFeed />
              )}
            </div>
          </div>
        )}
        {activeTab === "settings" && <MobileSettings />}
      </div>

      {/* Bottom tab bar */}
      <nav className="flex items-center justify-around shrink-0 border-t border-[var(--forge-border)] bg-[var(--forge-sidebar)] pb-[env(safe-area-inset-bottom)]" role="tablist" aria-label="Main navigation">
        <TabButton
          icon={MessageSquare}
          label="Messages"
          active={activeTab === "messages"}
          badge={totalUnread}
          onPress={() => { haptic("light"); setActiveTab("messages"); }}
        />
        <TabButton
          icon={Zap}
          label="Pipelines"
          active={activeTab === "pipelines"}
          badge={pipelineUnread}
          onPress={() => { haptic("light"); setActiveTab("pipelines"); }}
        />
        <TabButton
          icon={Bell}
          label="Activity"
          active={activeTab === "activity"}
          badge={approvalCount}
          onPress={() => { haptic("light"); setActiveTab("activity"); }}
        />
        <TabButton
          icon={Settings}
          label="Settings"
          active={activeTab === "settings"}
          onPress={() => { haptic("light"); setActiveTab("settings"); }}
        />
      </nav>

      {/* Mobile new pipeline (full-screen) */}
      {newPipelineModalOpen && (
        <MobileNewPipeline
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
              participants: [{ type: "user", id: "me", name: "You" }],
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
            openConversation(convId);
            closeNewPipelineModal();
          }}
        />
      )}
    </div>
  );
}

// ─── Tab Button ─────────────────────────────────────

function TabButton({
  icon: Icon,
  label,
  active,
  badge,
  onPress,
}: {
  icon: typeof MessageSquare;
  label: string;
  active: boolean;
  badge?: number;
  onPress: () => void;
}) {
  return (
    <button
      onClick={onPress}
      role="tab"
      aria-selected={active}
      aria-label={`${label}${badge && badge > 0 ? `, ${badge} notifications` : ""}`}
      className={cn(
        "flex flex-col items-center gap-0.5 py-2 px-4 min-w-[64px] transition-colors",
        active
          ? "text-[var(--forge-accent)]"
          : "text-[var(--forge-text-muted)]"
      )}
    >
      <div className="relative">
        <Icon className="w-5 h-5" />
        {badge != null && badge > 0 && (
          <span className="absolute -top-1.5 -right-2.5 bg-[var(--forge-accent)] text-white text-[9px] font-bold px-1 py-px rounded-full min-w-[14px] text-center leading-tight">
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </div>
      <span className="text-[10px] font-medium">{label}</span>
    </button>
  );
}
