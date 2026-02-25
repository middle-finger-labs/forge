import { ConversationView } from "@/components/conversation/ConversationView";
import { PipelineChannel } from "@/components/pipeline/PipelineChannel";
import { useConversationStore } from "@/stores/conversationStore";
import type { PipelineRun } from "@/types/pipeline";

interface MainPanelProps {
  pipelineRuns: PipelineRun[];
}

export function MainPanel({ pipelineRuns }: MainPanelProps) {
  const { activeConversationId, conversations } = useConversationStore();

  const active = activeConversationId
    ? conversations[activeConversationId]
    : undefined;

  // Route pipeline conversations to PipelineChannel
  if (active?.type === "pipeline") {
    const pipelineRun = active.pipelineId
      ? pipelineRuns.find((r) => r.id === active.pipelineId)
      : undefined;

    return (
      <PipelineChannel
        conversationId={active.id}
        pipelineRun={pipelineRun}
      />
    );
  }

  // All other conversations use the standard ConversationView
  return <ConversationView pipelineRuns={pipelineRuns} />;
}
