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
import type { ConversationIdentity } from '../types';

type ChatRunPollingOptions = {
  summarizeDelegatedRun?: boolean;
  ignoreInitialApprovalRequired?: boolean;
  identity: ConversationIdentity;
};

type ChatRunMessagesRefresh = {
  is_processing?: boolean;
  processing_count?: number;
} | undefined;

type UseChatRunPollingOptions = {
  activePollIntervalMs: number;
  createDelegatedRunSummaryOptions: (
    identity: ConversationIdentity,
  ) => Parameters<typeof createDelegatedRunSummary>[1];
  forgetRunApprovalDetails: (runId: string) => void;
  isProcessingRef: { current: boolean };
  isConversationCurrent: (identity: ConversationIdentity) => boolean;
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
  isConversationCurrent,
  loadSessions,
  refreshMessages,
  rememberRunApprovalDetails,
  setIsProcessing,
  setProcessingCount,
  setStatus,
}: UseChatRunPollingOptions) {
  const pollingConversationIsCurrent = useCallback((options: ChatRunPollingOptions) => (
    Boolean(options.identity?.sessionId)
    && Number.isFinite(options.identity?.conversationToken)
    && isConversationCurrent(options.identity)
  ), [isConversationCurrent]);
  const pollAgentRunCompletion = useCallback(async (
    runId: string,
    options: ChatRunPollingOptions,
  ) => {
    const maxAttempts = 600;
    const interval = activePollIntervalMs;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (!pollingConversationIsCurrent(options)) return;
      try {
        const run = await getChatRunSnapshot(runId);
        if (!pollingConversationIsCurrent(options)) return;
        const status = normalizeRunStatus(run.status);
        const runLabel = chatRunLabel(run);
        if (status === 'approval_required' && options.ignoreInitialApprovalRequired && attempt < 3) {
          await new Promise((resolve) => setTimeout(resolve, interval));
          continue;
        }
        if (isChatRunTerminalStatus(status)) {
          const refreshed = await refreshMessages();
          if (!pollingConversationIsCurrent(options)) return;
          await loadSessions();
          if (!pollingConversationIsCurrent(options)) return;
          const chatStillProcessing = refreshed
            ? Boolean(refreshed.is_processing)
            : isProcessingRef.current;
          const chatProcessingCount = refreshed
            ? Math.max(0, Number(refreshed.processing_count || 0))
            : chatStillProcessing ? 1 : 0;
          if (status === 'approval_required') {
            rememberRunApprovalDetails(run);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
            setStatus(nextApprovalStatusText(run));
          } else {
            forgetRunApprovalDetails(runId);
            const delegatedSummary = options.summarizeDelegatedRun
              ? await createDelegatedRunSummary(
                runId,
                createDelegatedRunSummaryOptions(options.identity),
              )
              : { created: false, error: '', taskId: '', isProcessing: false, processingCount: 0 };
            if (!pollingConversationIsCurrent(options)) return;
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
      if (!pollingConversationIsCurrent(options)) return;
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
    if (!pollingConversationIsCurrent(options)) return;
    const refreshed = await refreshMessages();
    if (!pollingConversationIsCurrent(options)) return;
    await loadSessions();
    if (!pollingConversationIsCurrent(options)) return;
    const chatStillProcessing = refreshed
      ? Boolean(refreshed.is_processing)
      : isProcessingRef.current;
    const chatProcessingCount = refreshed
      ? Math.max(0, Number(refreshed.processing_count || 0))
      : chatStillProcessing ? 1 : 0;
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
    pollingConversationIsCurrent,
    refreshMessages,
    rememberRunApprovalDetails,
    setIsProcessing,
    setProcessingCount,
    setStatus,
  ]);

  const pollAgentRunInBackground = useCallback((
    runId: string,
    options: ChatRunPollingOptions,
  ) => {
    void pollAgentRunCompletion(runId, options).catch((error) => {
      console.error('后台轮询 Agent Run 状态失败:', error);
      if (pollingConversationIsCurrent(options)) {
        setStatus(error instanceof Error ? error.message : 'Agent 任务状态刷新失败');
      }
    });
  }, [pollAgentRunCompletion, pollingConversationIsCurrent, setStatus]);

  return {
    pollAgentRunCompletion,
    pollAgentRunInBackground,
  };
}
