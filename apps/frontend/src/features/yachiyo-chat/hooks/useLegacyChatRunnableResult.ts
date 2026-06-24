import { useCallback } from 'react';

import { legacyChatRunnableResult, type LegacyChatMessageResult } from '../api';
import { chatRunnableRunningStatusText, chatRunnableSettledStatusText } from '../taskStatusText';
import { yachiyoTaskRunId } from '../taskSnapshots';
import type { AgentTaskSnapshot } from '../types';

type UseLegacyChatRunnableResultOptions = {
  clearPendingReplyTask: () => void;
  expectPendingAssistantReply: (taskId: string) => void;
  loadSessions: () => Promise<void>;
  onRunning: () => void;
  onSettled: () => void;
  pollAgentRunInBackground: (runId: string) => void;
  refreshMessages: () => Promise<unknown>;
  refreshYachiyoTaskById: (taskId: string) => unknown;
  rememberYachiyoTasks: (tasks: Array<AgentTaskSnapshot | null | undefined>) => void;
  setStatus: (value: string) => void;
};

type HandleLegacyChatRunnableResultOptions = {
  refreshTaskSnapshot?: boolean;
};

export function useLegacyChatRunnableResult({
  clearPendingReplyTask,
  expectPendingAssistantReply,
  loadSessions,
  onRunning,
  onSettled,
  pollAgentRunInBackground,
  refreshMessages,
  refreshYachiyoTaskById,
  rememberYachiyoTasks,
  setStatus,
}: UseLegacyChatRunnableResultOptions) {
  const handleLegacyChatRunnableResult = useCallback(async (
    result: LegacyChatMessageResult,
    options: HandleLegacyChatRunnableResultOptions = {},
  ) => {
    const agentTask = legacyChatAgentTask(result);
    if (agentTask) {
      rememberYachiyoTasks([agentTask]);
      const taskId = String(agentTask.task_id || '').trim();
      const taskStatus = String(agentTask.status || result.status || '').trim();
      const taskRunId = yachiyoTaskRunId(agentTask) || String(result.run_id || '').trim() || taskId;
      if (taskId) expectPendingAssistantReply(taskId);
      if (isActiveAgentTaskStatus(taskStatus) && taskRunId) {
        setStatus(chatRunnableRunningStatusText('八千代'));
        onRunning();
        await refreshMessages();
        pollAgentRunInBackground(taskRunId);
        return true;
      }
      onSettled();
      setStatus(chatRunnableSettledStatusText({
        error: result.error || agentTask.summary || '',
        hasRunId: Boolean(taskRunId),
        label: '八千代',
        status: taskStatus,
      }));
      await refreshMessages();
      await loadSessions();
      return true;
    }

    const runnableResult = legacyChatRunnableResult(result);
    if (!runnableResult.runnableCommand) return false;

    clearPendingReplyTask();
    const resultRunId = runnableResult.runId;
    const resultRunStatus = runnableResult.status;
    const runnableLabel = runnableResult.label;

    if (resultRunStatus === 'processing' && resultRunId) {
      setStatus(chatRunnableRunningStatusText(runnableLabel));
      onRunning();
      if (options.refreshTaskSnapshot) void refreshYachiyoTaskById(resultRunId);
      await refreshMessages();
      pollAgentRunInBackground(resultRunId);
      return true;
    }

    if (options.refreshTaskSnapshot && resultRunId) void refreshYachiyoTaskById(resultRunId);
    onSettled();
    setStatus(chatRunnableSettledStatusText({
      error: runnableResult.error,
      hasRunId: Boolean(resultRunId),
      label: runnableLabel,
      status: resultRunStatus,
    }));
    await refreshMessages();
    await loadSessions();
    return true;
  }, [
    clearPendingReplyTask,
    expectPendingAssistantReply,
    loadSessions,
    onRunning,
    onSettled,
    pollAgentRunInBackground,
    refreshMessages,
    refreshYachiyoTaskById,
    rememberYachiyoTasks,
    setStatus,
  ]);

  return {
    handleLegacyChatRunnableResult,
  };
}

function legacyChatAgentTask(result: LegacyChatMessageResult): AgentTaskSnapshot | null {
  const task = result.agent_task;
  if (!task || typeof task !== 'object') return null;
  return String(task.task_id || '').trim() ? task : null;
}

function isActiveAgentTaskStatus(status: string): boolean {
  return ['processing', 'queued', 'running'].includes(String(status || '').trim());
}
