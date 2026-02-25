import { useConversationStore } from "@/stores/conversationStore";

/** Convenience hook for the active conversation and its messages */
export function useConversation() {
  const {
    conversations,
    activeConversationId,
    messages,
    setActiveConversation,
    addMessage,
    markRead,
  } = useConversationStore();

  const activeConversation = activeConversationId
    ? conversations[activeConversationId]
    : undefined;

  const activeMessages = activeConversationId
    ? (messages[activeConversationId] ?? [])
    : [];

  return {
    conversations: Object.values(conversations),
    activeConversation,
    activeConversationId,
    activeMessages,
    setActiveConversation,
    addMessage,
    markRead,
  };
}
