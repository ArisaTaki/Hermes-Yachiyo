import { useCallback } from 'react';

import { legacyChatRunnableResult, type LegacyChatMessageResult } from '../api';
import { chatRunnableRunningStatusText, chatRunnableSettledStatusText } from '../taskStatusText';

type UseLegacyChatRunnableResultOptions = {
  clearPendingReplyTask: () => void;
  loadSessions: () => Promise<void>;
  onRunning: () => void;
  onSettled: () => void;
  pollAgentRunInBackground: (runId: string) => void;
  refreshMessages: () => Promise<unknown>;
  refreshYachiyoTaskById: (taskId: string) => unknown;
  setStatus: (value: string) => void;
};

type HandleLegacyChatRunnableResultOptions = {
  refreshTaskSnapshot?: boolean;
};

export function useLegacyChatRunnableResult({
  clearPendingReplyTask,
  loadSessions,
  onRunning,
  onSettled,
  pollAgentRunInBackground,
  refreshMessages,
  refreshYachiyoTaskById,
  setStatus,
}: UseLegacyChatRunnableResultOptions) {
  const handleLegacyChatRunnableResult = useCallback(async (
    result: LegacyChatMessageResult,
    options: HandleLegacyChatRunnableResultOptions = {},
  ) => {
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
    loadSessions,
    onRunning,
    onSettled,
    pollAgentRunInBackground,
    refreshMessages,
    refreshYachiyoTaskById,
    setStatus,
  ]);

  return {
    handleLegacyChatRunnableResult,
  };
}
