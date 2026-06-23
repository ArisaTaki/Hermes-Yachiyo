import { useCallback } from 'react';

import { startYachiyoTask } from '../api';
import { chatRunnableRunningStatusText, chatRunnableSettledStatusText } from '../taskStatusText';
import type { AgentTaskSnapshot } from '../types';

type StartPublicYachiyoTaskRequest = {
  clientMessageId: string;
  conversationId: string | null;
  metadata?: Record<string, unknown>;
  prompt: string;
  runnableId?: string | null;
  runnableKind?: 'agent' | 'workflow' | 'main';
};

type UseYachiyoTaskSubmitOptions = {
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
    clientMessageId,
    conversationId,
    metadata,
    prompt,
    runnableId,
    runnableKind,
  }: StartPublicYachiyoTaskRequest) => {
    try {
      const runnableLabel = runnableKind === 'workflow' ? 'Workflow' : runnableKind === 'agent' ? 'Agent' : '八千代';
      const cleanRunnableId = String(runnableId || '').trim();
      const task = await startYachiyoTask({
        prompt,
        conversation_id: conversationId,
        ...(runnableKind === 'workflow' && cleanRunnableId
          ? { workflow_id: cleanRunnableId }
          : {}),
        ...(runnableKind === 'agent' && cleanRunnableId
          ? { agent_id: cleanRunnableId }
          : {}),
        metadata: {
          client_message_id: clientMessageId,
          source: 'chat',
          runnable_kind: runnableKind || 'main',
          ...metadata,
        },
      });
      rememberYachiyoTasks([task]);
      onAccepted();
      if (task.status === 'running' && task.task_id) {
        setStatus(chatRunnableRunningStatusText(runnableLabel));
        onRunning();
        await refreshMessages();
        pollAgentRunInBackground(task.task_id);
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
