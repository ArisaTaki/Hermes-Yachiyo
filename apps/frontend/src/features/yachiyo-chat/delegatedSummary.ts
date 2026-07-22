import { apiPost } from '../../lib/bridge';
import type { ConversationIdentity, DelegatedRunSummaryResult } from './types';

type DelegatedRunSummaryPayload = {
  ok?: boolean;
  error?: string;
  message_id?: string;
  summary_created?: boolean;
  task_id?: string;
  run_id?: string;
  run_group_id?: string;
  run_status?: string;
  source_task_id?: string;
};

type DelegatedRunSummaryRefresh = {
  is_processing?: boolean;
  processing_count?: number;
} | undefined;

type CreateDelegatedRunSummaryOptions = {
  expectPendingAssistantReply: (taskId: string) => void;
  identity: ConversationIdentity;
  isConversationCurrent: (identity: ConversationIdentity) => boolean;
  loadSessions: () => Promise<void>;
  refreshMessages: () => Promise<DelegatedRunSummaryRefresh>;
};

export async function createDelegatedRunSummary(
  runId: string,
  {
    expectPendingAssistantReply,
    identity,
    isConversationCurrent,
    loadSessions,
    refreshMessages,
  }: CreateDelegatedRunSummaryOptions,
): Promise<DelegatedRunSummaryResult> {
  const emptyResult = (): DelegatedRunSummaryResult => ({
    created: false,
    error: '',
    taskId: '',
    isProcessing: false,
    processingCount: 0,
  });
  if (!identity.sessionId || !isConversationCurrent(identity)) return emptyResult();
  try {
    const summary = await apiPost<DelegatedRunSummaryPayload>('/ui/chat/delegated-run-summary', {
      run_id: runId,
      conversation_id: identity.sessionId,
    });
    if (!isConversationCurrent(identity)) return emptyResult();
    if (summary.ok === false) throw new Error(summary.error || '创建主模型整理任务失败');
    const taskId = String(summary.task_id || '');
    const created = Boolean(summary.summary_created && taskId);
    let refreshed: DelegatedRunSummaryRefresh;
    if (created) {
      if (!isConversationCurrent(identity)) return emptyResult();
      expectPendingAssistantReply(taskId);
      refreshed = await refreshMessages();
      if (!isConversationCurrent(identity)) return emptyResult();
      await loadSessions();
      if (!isConversationCurrent(identity)) return emptyResult();
    }
    const refreshedProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
    return {
      created,
      error: '',
      taskId,
      isProcessing: created ? (refreshed ? Boolean(refreshed.is_processing || refreshedProcessingCount > 0) : true) : false,
      processingCount: created ? (refreshed ? refreshedProcessingCount : 1) : 0,
    };
  } catch (error) {
    if (!isConversationCurrent(identity)) return emptyResult();
    return {
      created: false,
      error: error instanceof Error ? error.message : '创建主模型整理任务失败',
      taskId: '',
      isProcessing: false,
      processingCount: 0,
    };
  }
}
