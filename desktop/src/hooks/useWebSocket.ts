import { useEffect, useRef } from "react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useConversationStore } from "@/stores/conversationStore";
import { getForgeWS, type ForgeWebSocket } from "@/services/ws";

/**
 * Connects the ForgeWebSocket and wires events into stores.
 * Call once at the app root level.
 */
export function useWebSocket() {
  const { serverUrl, connectionStatus, authToken } = useConnectionStore();
  const wsRef = useRef<ForgeWebSocket | null>(null);

  useEffect(() => {
    if (!serverUrl || connectionStatus !== "authenticated") return;

    const ws = getForgeWS();
    wsRef.current = ws;

    const wsUrl = serverUrl.replace(/^http/, "ws") + "/ws";
    ws.connect(wsUrl, authToken ?? undefined);

    // Wire incoming messages into the conversation store
    const unsubMessage = ws.on("message", (msg) => {
      useConversationStore.getState().addMessage(msg);
    });

    const unsubAgentStatus = ws.on("agent_status", (agent) => {
      useConversationStore.getState().updateAgentStatus(
        agent.role,
        agent.status,
        agent.currentTask
      );
    });

    return () => {
      unsubMessage();
      unsubAgentStatus();
      ws.disconnect();
    };
  }, [serverUrl, connectionStatus, authToken]);

  return { connectionStatus };
}
