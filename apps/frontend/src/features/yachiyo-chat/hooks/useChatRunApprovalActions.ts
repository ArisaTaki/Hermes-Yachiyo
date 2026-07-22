import { useCallback } from 'react';

import {
  approvalIdFromPending,
  isWorkflowApprovalDetails,
  messageApprovalId,
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
import type { ChatMessage, ConversationIdentity } from '../types';

type ChatRunApprovalMessagesRefresh = {
  is_processing?: boolean;
  processing_count?: number;
} | undefined;

type ChatRunApprovalPollingOptions = {
  identity: ConversationIdentity;
  summarizeDelegatedRun?: boolean;
  ignoreInitialApprovalRequired?: boolean;
};

type UseChatRunApprovalActionsOptions = {
  approvalActionMessageId: string;
  createDelegatedRunSummaryOptions: (
    identity: ConversationIdentity,
  ) => Parameters<typeof createDelegatedRunSummary>[1];
  focusComposerSoon: () => void;
  forgetRunApprovalDetails: (runId: string) => void;
  getConversationIdentity: () => ConversationIdentity | null;
  isProcessingRef: { current: boolean };
  isConversationCurrent: (identity: ConversationIdentity) => boolean;
  loadSessions: () => Promise<void>;
  pollAgentRunInBackground: (
    runId: string,
    options: ChatRunApprovalPollingOptions,
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
  approvalId: string;
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
  getConversationIdentity,
  isProcessingRef,
  isConversationCurrent,
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
  const refreshApprovalProjection = useCallback(async (identity: ConversationIdentity) => {
    if (!isConversationCurrent(identity)) return undefined;
    let refreshed: ChatRunApprovalMessagesRefresh;
    try {
      refreshed = await refreshMessages();
    } catch {
      refreshed = undefined;
    }
    if (!isConversationCurrent(identity)) return undefined;
    try {
      await loadSessions();
    } catch {
      // The mutation response remains authoritative when a projection refresh is unavailable.
    }
    if (!isConversationCurrent(identity)) return undefined;
    return refreshed;
  }, [isConversationCurrent, loadSessions, refreshMessages]);

  const resolveComposerApprovalItem = useCallback((composerItemId?: string) => {
    if (!composerItemId) return;
    setResolvedComposerApprovalIds((current) => (
      current.includes(composerItemId) ? current : [...current.slice(-20), composerItemId]
    ));
  }, [setResolvedComposerApprovalIds]);

  const resolveApprovalRun = useCallback(async ({
    action,
    approvalId,
    busyId,
    composerItemId,
    fallbackApprovalDetails,
    runId,
    summarizeDelegatedRun,
  }: ResolveApprovalRunOptions) => {
    if (!runId || approvalActionMessageId) return;
    if (!approvalId) {
      setStatus('审批信息已过期，请刷新后重试。');
      return;
    }
    const identity = getConversationIdentity();
    if (!identity) {
      setStatus('当前会话尚未准备好，请稍后再试');
      return;
    }
    setApprovalActionMessageId(busyId);
    setStatus(action === 'approve' ? '正在批准工具调用...' : '正在拒绝工具调用...');
    try {
      if (action === 'approve') {
        const run = await approveChatRunApproval(runId, approvalId);
        if (!isConversationCurrent(identity)) return;
        const refreshed = await refreshApprovalProjection(identity);
        if (!isConversationCurrent(identity)) return;
        const chatStillProcessing = refreshed
          ? Boolean(refreshed.is_processing)
          : isProcessingRef.current;
        const chatProcessingCount = refreshed
          ? Math.max(0, Number(refreshed.processing_count || 0))
          : chatStillProcessing ? 1 : 0;
        const runStatus = normalizeRunStatus(run.status);
        const nextApprovalId = approvalIdFromPending(run.pending_approval);
        const approvalGenerationAdvanced = (
          runStatus !== 'approval_required'
          || nextApprovalId !== approvalId
        );
        if (approvalGenerationAdvanced) {
          resolveComposerApprovalItem(composerItemId);
        }
        if (runStatus === 'approval_required') {
          rememberRunApprovalDetails(run, fallbackApprovalDetails);
          isProcessingRef.current = true;
          setIsProcessing(true);
          setProcessingCount(Math.max(1, chatProcessingCount));
          setStatus(
            nextApprovalId && nextApprovalId !== approvalId
              ? nextApprovalStatusText(run)
              : '审批状态尚未推进，请刷新后重试。',
          );
          return;
        }
        forgetRunApprovalDetails(runId);
        const approvalTargetLabel = fallbackApprovalDetails && isWorkflowApprovalDetails(fallbackApprovalDetails)
          ? 'Workflow'
          : 'Agent';
        const nextProcessing = runStatus === 'processing' || chatStillProcessing;
        isProcessingRef.current = nextProcessing;
        setIsProcessing(nextProcessing);
        setProcessingCount(nextProcessing ? Math.max(1, chatProcessingCount) : chatProcessingCount);
        setStatus(
          runStatus === 'processing'
            ? `已批准，${approvalTargetLabel} 正在继续执行...`
            : '审批已批准，正在刷新执行结果...',
        );
        pollAgentRunInBackground(runId, {
          identity,
          summarizeDelegatedRun,
          ignoreInitialApprovalRequired: true,
        });
        return;
      }
      const run = await rejectChatRunApproval(runId, approvalId, 'Rejected from chat');
      if (!isConversationCurrent(identity)) return;
      const refreshed = await refreshApprovalProjection(identity);
      if (!isConversationCurrent(identity)) return;
      const chatStillProcessing = refreshed
        ? Boolean(refreshed.is_processing)
        : isProcessingRef.current;
      const chatProcessingCount = refreshed
        ? Math.max(0, Number(refreshed.processing_count || 0))
        : chatStillProcessing ? 1 : 0;
      const runStatus = normalizeRunStatus(run.status);
      let delegatedSummary = { created: false, error: '', taskId: '', isProcessing: false, processingCount: 0 };
      if (summarizeDelegatedRun && ['completed', 'failed', 'cancelled'].includes(runStatus)) {
        delegatedSummary = await createDelegatedRunSummary(
          runId,
          createDelegatedRunSummaryOptions(identity),
        );
        if (!isConversationCurrent(identity)) return;
      }
      const nextApprovalId = approvalIdFromPending(run.pending_approval);
      if (runStatus !== 'approval_required' || nextApprovalId !== approvalId) {
        resolveComposerApprovalItem(composerItemId);
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
          pollAgentRunInBackground(runId, { identity, summarizeDelegatedRun });
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
      await refreshApprovalProjection(identity);
      if (isConversationCurrent(identity)) {
        setStatus(error instanceof Error ? error.message : '处理审批失败');
      }
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }, [
    approvalActionMessageId,
    createDelegatedRunSummaryOptions,
    focusComposerSoon,
    forgetRunApprovalDetails,
    getConversationIdentity,
    isProcessingRef,
    isConversationCurrent,
    pollAgentRunInBackground,
    refreshApprovalProjection,
    rememberRunApprovalDetails,
    resolveComposerApprovalItem,
    setApprovalActionMessageId,
    setIsProcessing,
    setProcessingCount,
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
      approvalId: messageApprovalId(message),
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
      approvalId: String(item.approvalId || '').trim(),
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
