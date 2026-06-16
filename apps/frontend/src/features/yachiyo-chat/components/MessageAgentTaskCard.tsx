import {
  agentTaskSnapshotFromMessage,
  type YachiyoTaskChatMessage,
} from '../taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot } from '../types';
import { AgentTaskCard } from './AgentTaskCard';

export function MessageAgentTaskCard({
  busy,
  displayContent,
  hidden = false,
  message,
  onApproveApproval,
  onCancelTask,
  onOpenStudio,
  onRejectApproval,
  publicTaskSnapshot = null,
}: {
  busy: boolean;
  displayContent: string;
  hidden?: boolean;
  message: YachiyoTaskChatMessage;
  onApproveApproval: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void;
  onCancelTask: (task: AgentTaskSnapshot) => void;
  onOpenStudio: (runId: string | undefined, studioUrl?: string) => void;
  onRejectApproval: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void;
  publicTaskSnapshot?: AgentTaskSnapshot | null;
}) {
  if (hidden) return null;
  const task = publicTaskSnapshot || agentTaskSnapshotFromMessage(message, displayContent);
  if (!task) return null;
  return (
    <AgentTaskCard
      busy={busy}
      onApproveApproval={onApproveApproval}
      onCancelTask={onCancelTask}
      onOpenStudio={onOpenStudio}
      onRejectApproval={onRejectApproval}
      task={task}
    />
  );
}
