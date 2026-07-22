import { useCallback } from 'react';

import { startYachiyoTask } from '../api';
import { chatRunnableRunningStatusText, chatRunnableSettledStatusText } from '../taskStatusText';
import type { AgentTaskSnapshot, ConversationIdentity, PendingAttachment } from '../types';

const MAIN_CHAT_AGENT_ID = 'builtin:yachiyo-main';

type StartPublicYachiyoTaskRequest = {
  clientMessageId: string;
  identity: ConversationIdentity;
  attachments?: PendingAttachment[];
  metadata?: Record<string, unknown>;
  prompt: string;
  runnableId?: string | null;
  runnableKind?: 'agent' | 'workflow' | 'group' | 'main';
};

type UseYachiyoTaskSubmitOptions = {
  expectPendingAssistantReply: (taskId: string) => void;
  isConversationCurrent: (identity: ConversationIdentity) => boolean;
  loadSessions: () => Promise<void>;
  onAccepted: (clientMessageId: string) => void;
  onRunning: () => void;
  onSettled: () => void;
  pollAgentRunInBackground: (
    runId: string,
    options: {
      identity: ConversationIdentity;
      summarizeDelegatedRun?: boolean;
      ignoreInitialApprovalRequired?: boolean;
    },
  ) => void;
  refreshMessages: () => Promise<unknown>;
  rememberYachiyoTasks: (tasks: Array<AgentTaskSnapshot | null | undefined>) => void;
  setStatus: (value: string) => void;
};

export function useYachiyoTaskSubmit({
  expectPendingAssistantReply,
  isConversationCurrent,
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
    identity,
    metadata,
    prompt,
    runnableId,
    runnableKind,
  }: StartPublicYachiyoTaskRequest) => {
    let accepted = false;
    const conversationStillCurrent = () => (
      Boolean(identity.sessionId) && isConversationCurrent(identity)
    );
    if (!conversationStillCurrent()) return false;
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
        conversation_id: identity.sessionId,
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
      accepted = true;
      if (!conversationStillCurrent()) return true;
      rememberYachiyoTasks([task]);
      onAccepted(clientMessageId);
      const taskId = String(task.task_id || '').trim();
      if (taskId) expectPendingAssistantReply(taskId);
      if (task.status === 'running' && taskId) {
        setStatus(chatRunnableRunningStatusText(runnableLabel));
        onRunning();
        pollAgentRunInBackground(taskId, {
          identity,
        });
        const refreshed = await refreshMessages();
        if (conversationStillCurrent() && !refreshed) setStatus('任务已接收，消息正在同步…');
        return true;
      }
      onSettled();
      setStatus(chatRunnableSettledStatusText({
        hasRunId: Boolean(task.task_id),
        label: runnableLabel,
        status: task.status,
      }));
      const refreshed = await refreshMessages();
      await loadSessions();
      if (conversationStillCurrent() && !refreshed) setStatus('任务已接收，消息正在同步…');
      return true;
    } catch {
      if (accepted) {
        if (conversationStillCurrent()) setStatus('任务已接收，消息正在同步…');
        return true;
      }
      // Fall through to the legacy Chat API with the same idempotency key.
      return false;
    }
  }, [
    loadSessions,
    expectPendingAssistantReply,
    isConversationCurrent,
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
