import { useCallback } from 'react';

import {
  isWorkflowApprovalDetails,
  nextApprovalStatusText,
  type ComposerApprovalItem,
} from '../approvalItems';
import type { ApprovalRequestDetails } from '../components/MessageApprovalRequestCard';
import { createDelegatedRunSummary } from '../delegatedSummary';
import { messageRunId, normalizeRunStatus } from '../messageState';
import {
  chatApprovalRejectionCompletionStatusText,
  chatRunCompletionProcessingState,
} from '../runPolling';
import { approveChatRunApproval, rejectChatRunApproval } from '../runSnapshots';
import type { ChatMessage } from '../types';

type ChatRunApprovalMessagesRefresh = {
  is_processing?: boolean;
  processing_count?: number;
} | undefined;

type ChatRunApprovalPollingOptions = {
  summarizeDelegatedRun?: boolean;
  ignoreInitialApprovalRequired?: boolean;
};

type UseChatRunApprovalActionsOptions = {
  approvalActionMessageId: string;
  createDelegatedRunSummaryOptions: () => Parameters<typeof createDelegatedRunSummary>[1];
  focusComposerSoon: () => void;
  forgetRunApprovalDetails: (runId: string) => void;
  isProcessingRef: { current: boolean };
  loadSessions: () => Promise<void>;
  pollAgentRunInBackground: (
    runId: string,
    options?: ChatRunApprovalPollingOptions,
  ) => void;
  refreshMessages: () => Promise<ChatRunApprovalMessagesRefresh>;
  rememberRunApprovalDetails: (
    run: Parameters<typeof nextApprovalStatusText>[0],
    fallbackDetails?: ApprovalRequestDetails | null,
  ) => void;
  setApprovalActionMessageId: (value: string) => void;
  setIsProcessing: (value: boolean) => void;
  setProcessingCount: (value: number | ((current: number) => number)) => void;
  setResolvedComposerApprovalIds: (updater: (current: string[]) => string[]) => void;
  setStatus: (value: string) => void;
};

type ResolveApprovalRunOptions = {
  action: 'approve' | 'reject';
  busyId: string;
  composerItemId?: string;
  fallbackApprovalDetails?: ApprovalRequestDetails;
  runId: string;
  summarizeDelegatedRun?: boolean;
};

export function useChatRunApprovalActions({
  approvalActionMessageId,
  createDelegatedRunSummaryOptions,
  focusComposerSoon,
  forgetRunApprovalDetails,
  isProcessingRef,
  loadSessions,
  pollAgentRunInBackground,
  refreshMessages,
  rememberRunApprovalDetails,
  setApprovalActionMessageId,
  setIsProcessing,
  setProcessingCount,
  setResolvedComposerApprovalIds,
  setStatus,
}: UseChatRunApprovalActionsOptions) {
  const resolveApprovalRun = useCallback(async ({
    action,
    busyId,
    composerItemId,
    fallbackApprovalDetails,
    runId,
    summarizeDelegatedRun,
  }: ResolveApprovalRunOptions) => {
    if (!runId || approvalActionMessageId) return;
    setApprovalActionMessageId(busyId);
    setStatus(action === 'approve' ? '正在批准工具调用...' : '正在拒绝工具调用...');
    if (action === 'approve') {
      const approvalPromise = approveChatRunApproval(runId);
      const approvalTargetLabel = fallbackApprovalDetails && isWorkflowApprovalDetails(fallbackApprovalDetails) ? 'Workflow' : 'Agent';
      if (composerItemId) {
        setResolvedComposerApprovalIds((current) => (
          current.includes(composerItemId) ? current : [...current.slice(-20), composerItemId]
        ));
      }
      forgetRunApprovalDetails(runId);
      setIsProcessing(true);
      isProcessingRef.current = true;
      setProcessingCount((current) => Math.max(1, current || 1));
      setStatus(`已批准，${approvalTargetLabel} 正在继续执行...`);
      setApprovalActionMessageId('');
      pollAgentRunInBackground(runId, { summarizeDelegatedRun, ignoreInitialApprovalRequired: true });
      void approvalPromise
        .then(async (run) => {
          const refreshed = await refreshMessages();
          await loadSessions();
          const chatStillProcessing = Boolean(refreshed?.is_processing);
          const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
          const runStatus = normalizeRunStatus(run.status);
          if (runStatus === 'approval_required') {
            rememberRunApprovalDetails(run, fallbackApprovalDetails);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
            setStatus(nextApprovalStatusText(run));
          } else if (runStatus === 'processing') {
            forgetRunApprovalDetails(runId);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
          } else if (!chatStillProcessing) {
            isProcessingRef.current = false;
            setIsProcessing(false);
            setProcessingCount(chatProcessingCount);
          }
        })
        .catch(async (error) => {
          setStatus(error instanceof Error ? error.message : '批准失败');
          try {
            await refreshMessages();
            await loadSessions();
          } catch {
            // The approval error itself is the useful user-facing status here.
          }
        });
      return;
    }
    try {
      const run = await rejectChatRunApproval(runId, 'Rejected from chat');
      const refreshed = await refreshMessages();
      await loadSessions();
      const chatStillProcessing = Boolean(refreshed?.is_processing);
      const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
      const runStatus = normalizeRunStatus(run.status);
      let delegatedSummary = { created: false, error: '', taskId: '', isProcessing: false, processingCount: 0 };
      if (summarizeDelegatedRun && ['completed', 'failed', 'cancelled'].includes(runStatus)) {
        delegatedSummary = await createDelegatedRunSummary(runId, createDelegatedRunSummaryOptions());
      }
      if (composerItemId && runStatus !== 'approval_required') {
        setResolvedComposerApprovalIds((current) => (
          current.includes(composerItemId) ? current : [...current.slice(-20), composerItemId]
        ));
      }
      if (runStatus === 'processing' || runStatus === 'approval_required') {
        setIsProcessing(true);
        isProcessingRef.current = true;
        setProcessingCount(Math.max(1, chatProcessingCount));
        if (runStatus === 'approval_required') {
          rememberRunApprovalDetails(run, fallbackApprovalDetails);
          setStatus(nextApprovalStatusText(run));
        } else {
          forgetRunApprovalDetails(runId);
          setStatus('已拒绝，等待整理结果...');
          pollAgentRunInBackground(runId, { summarizeDelegatedRun });
        }
      } else {
        forgetRunApprovalDetails(runId);
        const { nextProcessing, nextProcessingCount } = chatRunCompletionProcessingState(
          delegatedSummary,
          chatStillProcessing,
          chatProcessingCount,
        );
        setIsProcessing(nextProcessing);
        isProcessingRef.current = nextProcessing;
        setProcessingCount(nextProcessingCount);
        setStatus(chatApprovalRejectionCompletionStatusText({
          chatStillProcessing,
          delegatedSummary,
          runStatus,
        }));
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '处理审批失败');
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }, [
    approvalActionMessageId,
    createDelegatedRunSummaryOptions,
    focusComposerSoon,
    forgetRunApprovalDetails,
    isProcessingRef,
    loadSessions,
    pollAgentRunInBackground,
    refreshMessages,
    rememberRunApprovalDetails,
    setApprovalActionMessageId,
    setIsProcessing,
    setProcessingCount,
    setResolvedComposerApprovalIds,
    setStatus,
  ]);

  const resolveApprovalMessage = useCallback(async (
    message: ChatMessage,
    action: 'approve' | 'reject',
  ) => {
    const runId = messageRunId(message);
    if (!message.id) return;
    await resolveApprovalRun({
      action,
      busyId: message.id,
      runId,
    });
  }, [resolveApprovalRun]);

  const resolveApprovalItem = useCallback(async (
    item: ComposerApprovalItem,
    action: 'approve' | 'reject',
  ) => {
    await resolveApprovalRun({
      action,
      busyId: item.id,
      composerItemId: item.id,
      runId: item.runId,
      fallbackApprovalDetails: item.details,
      summarizeDelegatedRun: item.source === 'activity',
    });
  }, [resolveApprovalRun]);

  return {
    resolveApprovalItem,
    resolveApprovalMessage,
  };
}
