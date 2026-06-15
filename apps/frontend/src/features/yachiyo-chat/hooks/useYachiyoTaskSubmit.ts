import { useCallback } from 'react';

import { startYachiyoTask } from '../api';
import type { AgentTaskSnapshot } from '../types';

type StartPublicYachiyoTaskRequest = {
  agentId: string;
  clientMessageId: string;
  conversationId: string | null;
  prompt: string;
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
    agentId,
    clientMessageId,
    conversationId,
    prompt,
  }: StartPublicYachiyoTaskRequest) => {
    try {
      const task = await startYachiyoTask({
        prompt,
        conversation_id: conversationId,
        agent_id: agentId,
        metadata: {
          client_message_id: clientMessageId,
          source: 'chat',
        },
      });
      rememberYachiyoTasks([task]);
      onAccepted();
      if (task.status === 'running' && task.task_id) {
        setStatus('Agent 执行中...');
        onRunning();
        await refreshMessages();
        pollAgentRunInBackground(task.task_id);
        return true;
      }
      onSettled();
      setStatus(task.status === 'waiting_approval'
        ? 'Agent 等待审批...'
        : task.status === 'completed'
          ? 'Agent Run 已处理。'
          : task.status === 'failed'
            ? 'Agent Run 失败。'
            : 'Agent/Workflow 指令已处理。');
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
