import { useCallback } from 'react';

import { approveYachiyoTask, cancelYachiyoTask, rejectYachiyoTask } from '../api';
import { yachiyoTaskRunId, yachiyoTaskStatusMessage } from '../taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot } from '../types';

type UseYachiyoTaskActionsOptions = {
  approvalActionMessageId: string;
  focusComposerSoon: () => void;
  loadSessions: () => Promise<void>;
  pollAgentRunInBackground: (
    runId: string,
    options?: { summarizeDelegatedRun?: boolean; ignoreInitialApprovalRequired?: boolean },
  ) => void;
  refreshMessages: () => Promise<unknown>;
  rememberYachiyoTasks: (tasks: Array<AgentTaskSnapshot | null | undefined>) => void;
  setApprovalActionMessageId: (value: string) => void;
  setStatus: (value: string) => void;
};

export function useYachiyoTaskActions({
  approvalActionMessageId,
  focusComposerSoon,
  loadSessions,
  pollAgentRunInBackground,
  refreshMessages,
  rememberYachiyoTasks,
  setApprovalActionMessageId,
  setStatus,
}: UseYachiyoTaskActionsOptions) {
  const resolveYachiyoTaskApproval = useCallback(async (
    task: AgentTaskSnapshot,
    approval: ApprovalCardSnapshot,
    action: 'approve' | 'reject',
  ) => {
    if (!task.task_id || !approval.approval_id || approvalActionMessageId) return;
    const busyId = `task:${task.task_id}:${approval.approval_id}:${action}`;
    setApprovalActionMessageId(busyId);
    setStatus(action === 'approve' ? '正在批准 Agent 任务审批...' : '正在拒绝 Agent 任务审批...');
    try {
      const nextTask = action === 'approve'
        ? await approveYachiyoTask(task.task_id, approval.approval_id)
        : await rejectYachiyoTask(task.task_id, approval.approval_id, 'Rejected from chat task card');
      rememberYachiyoTasks([nextTask]);
      const nextRunId = yachiyoTaskRunId(nextTask) || approval.run_id || task.task_id;
      setStatus(yachiyoTaskStatusMessage(nextTask, action));
      await refreshMessages();
      await loadSessions();
      if (nextRunId && ['queued', 'running', 'waiting_approval'].includes(nextTask.status)) {
        pollAgentRunInBackground(nextRunId, { ignoreInitialApprovalRequired: action === 'approve' });
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '处理 Agent 任务审批失败');
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }, [
    approvalActionMessageId,
    focusComposerSoon,
    loadSessions,
    pollAgentRunInBackground,
    refreshMessages,
    rememberYachiyoTasks,
    setApprovalActionMessageId,
    setStatus,
  ]);

  const cancelYachiyoTaskFromCard = useCallback(async (task: AgentTaskSnapshot) => {
    if (!task.task_id || approvalActionMessageId) return;
    const busyId = `task:${task.task_id}:cancel`;
    setApprovalActionMessageId(busyId);
    setStatus('正在取消 Agent 任务...');
    try {
      const nextTask = await cancelYachiyoTask(task.task_id);
      rememberYachiyoTasks([nextTask]);
      setStatus(yachiyoTaskStatusMessage(nextTask, 'cancel'));
      await refreshMessages();
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '取消 Agent 任务失败');
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }, [
    approvalActionMessageId,
    focusComposerSoon,
    loadSessions,
    refreshMessages,
    rememberYachiyoTasks,
    setApprovalActionMessageId,
    setStatus,
  ]);

  return {
    cancelYachiyoTaskFromCard,
    resolveYachiyoTaskApproval,
  };
}
