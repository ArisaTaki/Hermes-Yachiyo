import {
  agentTaskHasVisibleExecution,
  agentTaskSnapshotFromMessage,
  type YachiyoTaskChatMessage,
} from '../taskSnapshots';
import type { TaskPermissionRecoveryAction } from '../taskPermissionRecovery';
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
  onRunRecoveryAction,
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
  onRunRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void;
  publicTaskSnapshot?: AgentTaskSnapshot | null;
}) {
  if (hidden || message.role !== 'assistant') return null;
  const publicTask = publicTaskSnapshot && agentTaskHasVisibleExecution(publicTaskSnapshot)
    ? publicTaskSnapshot
    : null;
  const messageTask = agentTaskSnapshotFromMessage(message, displayContent);
  const task = publicTask || (agentTaskHasVisibleExecution(messageTask, message) ? messageTask : null);
  if (!task) return null;
  return (
    <AgentTaskCard
      busy={busy}
      onApproveApproval={onApproveApproval}
      onCancelTask={onCancelTask}
      onOpenStudio={onOpenStudio}
      onRejectApproval={onRejectApproval}
      onRunRecoveryAction={onRunRecoveryAction}
      surface="chat"
      task={task}
    />
  );
}
