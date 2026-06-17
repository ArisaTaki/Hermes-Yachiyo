import { useCallback } from 'react';

import { nextApprovalStatusText, type ChatApprovalRun } from '../approvalItems';
import { createDelegatedRunSummary } from '../delegatedSummary';
import { normalizeRunStatus } from '../messageState';
import {
  chatRunCompletionProcessingState,
  chatRunCompletionStatusText,
  chatRunLabel,
  chatRunPollingTimeoutStatusText,
  chatRunProgressStatusText,
  isChatRunTerminalStatus,
} from '../runPolling';
import { getChatRunSnapshot } from '../runSnapshots';

type ChatRunPollingOptions = {
  summarizeDelegatedRun?: boolean;
  ignoreInitialApprovalRequired?: boolean;
};

type ChatRunMessagesRefresh = {
  is_processing?: boolean;
  processing_count?: number;
} | undefined;

type UseChatRunPollingOptions = {
  activePollIntervalMs: number;
  createDelegatedRunSummaryOptions: () => Parameters<typeof createDelegatedRunSummary>[1];
  forgetRunApprovalDetails: (runId: string) => void;
  isProcessingRef: { current: boolean };
  loadSessions: () => Promise<void>;
  refreshMessages: () => Promise<ChatRunMessagesRefresh>;
  rememberRunApprovalDetails: (run: ChatApprovalRun) => void;
  setIsProcessing: (value: boolean) => void;
  setProcessingCount: (value: number) => void;
  setStatus: (value: string) => void;
};

export function useChatRunPolling({
  activePollIntervalMs,
  createDelegatedRunSummaryOptions,
  forgetRunApprovalDetails,
  isProcessingRef,
  loadSessions,
  refreshMessages,
  rememberRunApprovalDetails,
  setIsProcessing,
  setProcessingCount,
  setStatus,
}: UseChatRunPollingOptions) {
  const pollAgentRunCompletion = useCallback(async (
    runId: string,
    options: ChatRunPollingOptions = {},
  ) => {
    const maxAttempts = 600;
    const interval = activePollIntervalMs;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const run = await getChatRunSnapshot(runId);
        const status = normalizeRunStatus(run.status);
        const runLabel = chatRunLabel(run);
        if (status === 'approval_required' && options.ignoreInitialApprovalRequired && attempt < 3) {
          await new Promise((resolve) => setTimeout(resolve, interval));
          continue;
        }
        if (isChatRunTerminalStatus(status)) {
          const refreshed = await refreshMessages();
          await loadSessions();
          const chatStillProcessing = Boolean(refreshed?.is_processing);
          const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
          if (status === 'approval_required') {
            rememberRunApprovalDetails(run);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
            setStatus(nextApprovalStatusText(run));
          } else {
            forgetRunApprovalDetails(runId);
            const delegatedSummary = options.summarizeDelegatedRun
              ? await createDelegatedRunSummary(runId, createDelegatedRunSummaryOptions())
              : { created: false, error: '', taskId: '', isProcessing: false, processingCount: 0 };
            const { nextProcessing, nextProcessingCount } = chatRunCompletionProcessingState(
              delegatedSummary,
              chatStillProcessing,
              chatProcessingCount,
            );
            isProcessingRef.current = nextProcessing;
            setIsProcessing(nextProcessing);
            setProcessingCount(nextProcessingCount);
            setStatus(chatRunCompletionStatusText({
              chatStillProcessing,
              delegatedSummary,
              runLabel,
              status,
            }));
          }
          return;
        }
        if (attempt % 10 === 0) {
          setStatus(chatRunProgressStatusText(runLabel, attempt, interval));
        }
      } catch (error) {
        console.error('轮询 Agent Run 状态失败:', error);
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
    const refreshed = await refreshMessages();
    await loadSessions();
    const chatStillProcessing = Boolean(refreshed?.is_processing);
    const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
    isProcessingRef.current = chatStillProcessing;
    setIsProcessing(chatStillProcessing);
    setProcessingCount(chatProcessingCount);
    setStatus(chatRunPollingTimeoutStatusText(chatStillProcessing));
  }, [
    activePollIntervalMs,
    createDelegatedRunSummaryOptions,
    forgetRunApprovalDetails,
    isProcessingRef,
    loadSessions,
    refreshMessages,
    rememberRunApprovalDetails,
    setIsProcessing,
    setProcessingCount,
    setStatus,
  ]);

  const pollAgentRunInBackground = useCallback((
    runId: string,
    options: ChatRunPollingOptions = {},
  ) => {
    void pollAgentRunCompletion(runId, options).catch((error) => {
      console.error('后台轮询 Agent Run 状态失败:', error);
      setStatus(error instanceof Error ? error.message : 'Agent 任务状态刷新失败');
    });
  }, [pollAgentRunCompletion, setStatus]);

  return {
    pollAgentRunCompletion,
    pollAgentRunInBackground,
  };
}
