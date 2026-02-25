import { useEffect, useRef, useCallback } from "react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useOfflineStore, type NetworkStatus } from "@/stores/offlineStore";
import { getForgeWS } from "@/services/ws";
import { getForgeAPISync } from "@/services/api";

// ─── Constants ──────────────────────────────────────

const BACKGROUND_SYNC_INTERVAL_MS = 15 * 60 * 1000; // 15 minutes
const RECONNECT_DEBOUNCE_MS = 1000;
const FLUSH_RETRY_DELAY_MS = 2000;

// ─── Hook ───────────────────────────────────────────

/**
 * Manages offline detection, action queue flushing, cache hydration,
 * and background sync. Call once at the app root level.
 */
export function useOfflineSync() {
  const { serverUrl, authToken, connectionStatus } = useConnectionStore();
  const {
    networkStatus,
    setNetworkStatus,
    markOnline,
    actionQueue,
    dequeueAction,
    cacheConversations,
    cacheMessages,
    cachePipelines,
    cacheAgents,
    loadCachedConversations,
    loadCachedAgents,
    loadCachedMessages,
  } = useOfflineStore();
  const {
    setConversations,
    setMessages,
    setAgents,
    conversations,
    messages: allMessages,
  } = useConversationStore();

  const flushingRef = useRef(false);
  const syncTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Derive network status from connection status ──

  useEffect(() => {
    const statusMap: Record<string, NetworkStatus> = {
      authenticated: "online",
      connected: "online",
      connecting: "reconnecting",
      disconnected: "offline",
      error: "offline",
      unconfigured: "offline",
    };
    const mapped = statusMap[connectionStatus] ?? "offline";
    setNetworkStatus(mapped);

    if (mapped === "online") {
      markOnline();
    }
  }, [connectionStatus, setNetworkStatus, markOnline]);

  // ── Browser online/offline events (supplementary) ──

  useEffect(() => {
    const handleOnline = () => {
      // Browser reports online — attempt WS reconnect
      if (serverUrl && authToken) {
        const ws = getForgeWS();
        const wsUrl = serverUrl.replace(/^http/, "ws") + "/ws";
        ws.connect(wsUrl, authToken);
      }
    };

    const handleOffline = () => {
      setNetworkStatus("offline");
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [serverUrl, authToken, setNetworkStatus]);

  // ── Hydrate from cache on mount (before server data arrives) ──

  useEffect(() => {
    const cachedConvs = loadCachedConversations();
    if (cachedConvs && cachedConvs.length > 0) {
      setConversations(cachedConvs);

      // Also hydrate messages for each cached conversation
      for (const conv of cachedConvs) {
        const cachedMsgs = loadCachedMessages(conv.id);
        if (cachedMsgs && cachedMsgs.length > 0) {
          setMessages(conv.id, cachedMsgs);
        }
      }
    }

    const cachedAgents = loadCachedAgents();
    if (cachedAgents && cachedAgents.length > 0) {
      setAgents(cachedAgents);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Cache live data whenever it changes ───────────

  useEffect(() => {
    const convList = Object.values(conversations);
    if (convList.length > 0) {
      cacheConversations(convList);
    }
  }, [conversations, cacheConversations]);

  useEffect(() => {
    for (const [convId, msgs] of Object.entries(allMessages)) {
      if (msgs.length > 0) {
        cacheMessages(convId, msgs);
      }
    }
  }, [allMessages, cacheMessages]);

  // ── Flush queued actions when back online ─────────

  const flushQueue = useCallback(async () => {
    if (flushingRef.current) return;
    if (!serverUrl || !authToken) return;
    if (actionQueue.length === 0) return;

    flushingRef.current = true;
    const api = getForgeAPISync(serverUrl, authToken);

    // Process queue in order
    for (const action of [...actionQueue]) {
      try {
        if (action.type === "message") {
          await api.sendMessage(
            action.payload.conversationId,
            action.payload.content,
          );
          dequeueAction(action.payload.id);
        } else if (action.type === "approval") {
          await api.approvePipeline(
            action.payload.pipelineId,
            action.payload.stage,
            action.payload.approved,
            action.payload.comment,
          );
          dequeueAction(action.payload.id);
        }
      } catch {
        // Failed to send — stop flushing, will retry later
        break;
      }
    }

    flushingRef.current = false;
  }, [serverUrl, authToken, actionQueue, dequeueAction]);

  // Trigger flush when network comes back online
  useEffect(() => {
    if (networkStatus === "online" && actionQueue.length > 0) {
      const timer = setTimeout(flushQueue, RECONNECT_DEBOUNCE_MS);
      return () => clearTimeout(timer);
    }
  }, [networkStatus, actionQueue.length, flushQueue]);

  // ── Pull latest state on foreground / reconnect ───

  const pullLatestState = useCallback(async () => {
    if (!serverUrl || !authToken) return;
    if (connectionStatus !== "authenticated") return;

    const api = getForgeAPISync(serverUrl, authToken);

    try {
      const [convs, pipelines, agents] = await Promise.all([
        api.getConversations(),
        api.getPipelines(),
        api.getAgentStatuses(),
      ]);

      setConversations(convs);
      cacheConversations(convs);

      // Pipeline data is cached separately
      cachePipelines(pipelines);

      setAgents(agents);
      cacheAgents(agents);

      // Pull messages for active conversations
      const activeConvId = useConversationStore.getState().activeConversationId;
      if (activeConvId) {
        const { messages: msgs } = await api.getMessages(activeConvId);
        setMessages(activeConvId, msgs);
        cacheMessages(activeConvId, msgs);
      }
    } catch {
      // Server unreachable — stay on cached data
    }
  }, [
    serverUrl,
    authToken,
    connectionStatus,
    setConversations,
    cacheConversations,
    cachePipelines,
    setAgents,
    cacheAgents,
    setMessages,
    cacheMessages,
  ]);

  // Pull on authentication
  useEffect(() => {
    if (connectionStatus === "authenticated") {
      pullLatestState();
    }
  }, [connectionStatus, pullLatestState]);

  // ── App visibility change (foreground/background) ──

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        // App came to foreground
        if (serverUrl && authToken) {
          // Reconnect WebSocket (may have dropped while backgrounded on iOS)
          const ws = getForgeWS();
          const wsUrl = serverUrl.replace(/^http/, "ws") + "/ws";
          ws.connect(wsUrl, authToken);

          // Pull latest data
          pullLatestState();

          // Flush any queued actions
          if (actionQueue.length > 0) {
            setTimeout(flushQueue, FLUSH_RETRY_DELAY_MS);
          }
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [serverUrl, authToken, pullLatestState, flushQueue, actionQueue.length]);

  // ── Background sync timer (every 15 min) ──────────

  useEffect(() => {
    if (connectionStatus !== "authenticated") {
      if (syncTimerRef.current) {
        clearInterval(syncTimerRef.current);
        syncTimerRef.current = null;
      }
      return;
    }

    syncTimerRef.current = setInterval(() => {
      pullLatestState();
    }, BACKGROUND_SYNC_INTERVAL_MS);

    return () => {
      if (syncTimerRef.current) {
        clearInterval(syncTimerRef.current);
        syncTimerRef.current = null;
      }
    };
  }, [connectionStatus, pullLatestState]);

  return {
    networkStatus,
    queuedCount: actionQueue.length,
    pullLatestState,
    flushQueue,
  };
}
