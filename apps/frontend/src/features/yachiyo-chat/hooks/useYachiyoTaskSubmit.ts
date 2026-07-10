import { useCallback } from 'react';

import { startYachiyoTask } from '../api';
import { chatRunnableRunningStatusText, chatRunnableSettledStatusText } from '../taskStatusText';
import type { AgentTaskSnapshot, PendingAttachment } from '../types';

const MAIN_CHAT_AGENT_ID = 'builtin:yachiyo-main';

type StartPublicYachiyoTaskRequest = {
  clientMessageId: string;
  conversationId: string | null;
  attachments?: PendingAttachment[];
  metadata?: Record<string, unknown>;
  prompt: string;
  runnableId?: string | null;
  runnableKind?: 'agent' | 'workflow' | 'group' | 'main';
};

type UseYachiyoTaskSubmitOptions = {
  expectPendingAssistantReply: (taskId: string) => void;
  loadSessions: () => Promise<void>;
  onAccepted: () => void;
  onRunning: () => void;
  onSettled: () => void;
  pollAgentRunInBackground: (
    runId: string,
    options?: { summarizeDelegatedRun?: boolean; ignoreInitialApprovalRequired?: boolean },
  ) => void;
  refreshMessages: () => Promise<unknown>;
  rememberYachiyoTasks: (tasks: Array<AgentTaskSnapshot | null | undefined>) => void;
  setStatus: (value: string) => void;
};

export function useYachiyoTaskSubmit({
  expectPendingAssistantReply,
  loadSessions,
  onAccepted,
  onRunning,
  onSettled,
  pollAgentRunInBackground,
  refreshMessages,
  rememberYachiyoTasks,
  setStatus,
}: UseYachiyoTaskSubmitOptions) {
  const startPublicYachiyoTask = useCallback(async ({
    attachments,
    clientMessageId,
    conversationId,
    metadata,
    prompt,
    runnableId,
    runnableKind,
  }: StartPublicYachiyoTaskRequest) => {
    try {
      const runnableLabel = runnableKind === 'workflow'
        ? 'Workflow'
        : runnableKind === 'group'
          ? 'Group'
          : runnableKind === 'agent'
            ? 'Agent'
            : '八千代';
      const cleanRunnableId = String(runnableId || (runnableKind === 'main' ? MAIN_CHAT_AGENT_ID : '')).trim();
      const task = await startYachiyoTask({
        prompt,
        conversation_id: conversationId,
        ...(attachments?.length ? { attachments } : {}),
        ...(runnableKind === 'workflow' && cleanRunnableId
          ? { workflow_id: cleanRunnableId }
          : {}),
        ...(runnableKind === 'group' && cleanRunnableId
          ? { group_id: cleanRunnableId }
          : {}),
        ...((runnableKind === 'agent' || runnableKind === 'main') && cleanRunnableId
          ? { agent_id: cleanRunnableId }
          : {}),
        metadata: {
          client_message_id: clientMessageId,
          attachment_count: attachments?.length || 0,
          source: 'chat',
          runnable_kind: runnableKind || 'main',
          ...metadata,
        },
      });
      rememberYachiyoTasks([task]);
      onAccepted();
      const taskId = String(task.task_id || '').trim();
      if (taskId) expectPendingAssistantReply(taskId);
      if (task.status === 'running' && taskId) {
        setStatus(chatRunnableRunningStatusText(runnableLabel));
        onRunning();
        await refreshMessages();
        pollAgentRunInBackground(taskId);
        return true;
      }
      onSettled();
      setStatus(chatRunnableSettledStatusText({
        hasRunId: Boolean(task.task_id),
        label: runnableLabel,
        status: task.status,
      }));
      await refreshMessages();
      await loadSessions();
      return true;
    } catch {
      // Fall through to the legacy Chat API with the same idempotency key.
      return false;
    }
  }, [
    loadSessions,
    expectPendingAssistantReply,
    onAccepted,
    onRunning,
    onSettled,
    pollAgentRunInBackground,
    refreshMessages,
    rememberYachiyoTasks,
    setStatus,
  ]);

  return {
    startPublicYachiyoTask,
  };
}
