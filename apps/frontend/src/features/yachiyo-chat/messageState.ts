import {
  approvalRequiredMessages,
  nextApprovalStatusText,
} from './approvalItems';
import { participantDisplayName } from './sessionState';
import { latestGroupAgentSummaryNotice } from './messageGroups';
import { studioRunUrl } from '../runtime-shared/studioLinks';
import type { ChatActivityEvent, ChatMessage } from './types';

export type YachiyoChatActivityEvent = ChatActivityEvent;
export type YachiyoChatMessage = ChatMessage;

const CONSUMER_ACTIVITY_LABEL_BY_PHASE: Record<string, string> = {
  task_start: '处理中...',
  reasoning: '正在思考...',
  thinking: '正在思考...',
  tool_start: '处理中...',
  tool_progress: '处理中...',
  tool_complete: '正在整理结果...',
  subagent: '处理中...',
  desktop_snapshot: '正在确认操作...',
  task_complete: '正在整理回复...',
  task_failed: '正在更新状态...',
  task_cancelled: '正在更新状态...',
};

export function messageText(message: YachiyoChatMessage) {
  return String(message.content || message.text || '');
}

export function isRetryableMessage(message: YachiyoChatMessage, messages: YachiyoChatMessage[]) {
  if (message.status !== 'failed' || !message.id) return false;
  if (message.role === 'assistant') return true;
  if (message.role !== 'user') return false;
  if (!message.task_id) return true;
  return !messages.some((candidate) => (
    candidate.role === 'assistant'
    && candidate.task_id === message.task_id
  ));
}

export function retrySourceUserMessage(
  message: YachiyoChatMessage,
  messages: YachiyoChatMessage[],
) {
  if (message.role === 'user') return message;
  const messageIndex = message.id
    ? messages.findIndex((candidate) => candidate.id === message.id)
    : messages.indexOf(message);
  const searchEnd = messageIndex >= 0 ? messageIndex : messages.length;
  const taskId = String(message.task_id || '').trim();
  if (taskId) {
    for (let index = searchEnd - 1; index >= 0; index -= 1) {
      const candidate = messages[index];
      if (candidate?.role === 'user' && candidate.task_id === taskId) return candidate;
    }
  }
  for (let index = searchEnd - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (candidate?.role === 'user') return candidate;
  }
  return null;
}

export function shouldShowPendingAssistantReply(
  messages: YachiyoChatMessage[],
  submitting: boolean,
) {
  if (!submitting) return false;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const role = message?.role;
    if (role === 'assistant') return message?.status === 'failed';
    if (role === 'user') return true;
  }
  return false;
}

export function messageMatchesPendingAssistantReply(message: YachiyoChatMessage, taskId: string) {
  return (
    message.role === 'assistant'
    && message.task_id === taskId
    && (
      message.status === 'processing'
      || Boolean(messageText(message).trim())
      || Boolean(message.activity_events?.length)
    )
  );
}

export function messageErrorText(message: YachiyoChatMessage) {
  return String(
    message.error || message.content || message.text || '任务执行失败',
  ).trim();
}

export function normalizeRunStatus(status?: unknown) {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

export function messageRunStatus(message?: YachiyoChatMessage | null) {
  return normalizeRunStatus(message?.metadata?.run_status || message?.metadata?.workflow_status || '');
}

export function messageRunId(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.run_id || message?.metadata?.workflow_run_id || '').trim();
}

export function messageSender(message?: YachiyoChatMessage | null) {
  return message?.metadata?.sender || null;
}

export function messageRoleLabel(message: YachiyoChatMessage) {
  const role = message.role || 'system';
  if (role === 'user') return '你';
  if (role === 'assistant') {
    const sender = messageSender(message);
    if (sender?.kind === 'agent' || sender?.kind === 'workflow') {
      return participantDisplayName(sender) || 'Agent';
    }
    return 'Yachiyo';
  }
  return '系统';
}

export function messageHasRunContext(message?: YachiyoChatMessage | null) {
  const kind = String(message?.metadata?.runnable_kind || '').trim();
  return Boolean(messageRunId(message) || kind === 'agent' || kind === 'workflow');
}

export function messageRunProgressTitle(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.run_progress_title || 'Agent 正在执行');
}

export function messageRunProgressDetail(message: YachiyoChatMessage | null | undefined, progressName: string) {
  return String(message?.metadata?.run_progress_detail || `${progressName} 正在继续处理当前任务。`);
}

export function messageRunProgressRunnableKind(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.runnable_kind || message?.metadata?.sender?.kind || '').trim();
}

export function messageRunProgressRunnableId(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.runnable_id || message?.metadata?.sender?.id || '').trim();
}

export function messageRunProgressRunGroupId(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.run_group_id || '').trim();
}

export function latestFailedMessage(messages: YachiyoChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const status = messages[index]?.status;
    if (!status) continue;
    if (status === 'failed') return messages[index];
    if (status === 'pending' || status === 'processing' || status === 'completed') {
      return null;
    }
  }
  return null;
}

export function latestVisibleActivity(messages: YachiyoChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const events = messages[index]?.activity_events || [];
    if (events.length) return events[0];
    if (messages[index]?.progress_label) {
      return {
        title: messages[index]?.progress_label,
        status: messages[index]?.status,
        created_at: messages[index]?.created_at,
      } as YachiyoChatActivityEvent;
    }
  }
  return null;
}

export function activityLabel(event?: YachiyoChatActivityEvent | null) {
  if (!event) return '';
  const phase = String(event.phase || '').trim().toLowerCase();
  return CONSUMER_ACTIVITY_LABEL_BY_PHASE[phase] || '处理中...';
}

export function activityRunId(event?: YachiyoChatActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
}

export function activityGroupRunId(event?: YachiyoChatActivityEvent | null) {
  return String(event?.metadata?.run_group_id || event?.metadata?.group_dispatch_run_group_id || '').trim();
}

export function activityRunDetailTarget(event?: YachiyoChatActivityEvent | null) {
  const runId = activityRunId(event);
  const groupRunId = activityGroupRunId(event);
  return {
    groupRunId,
    runId,
    studioUrl: runId ? studioRunUrl(runId, { groupRunId }) || '' : '',
  };
}

export function compactStatusText(text: string, maxLength = 96) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '任务执行失败';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

export function chatStatusLabel(
  processing: boolean,
  failed: YachiyoChatMessage | null,
  messages: YachiyoChatMessage[],
  processingCount = 0,
) {
  const summaryNotice = latestGroupAgentSummaryNotice(messages);
  if (processing) {
    const approval = latestApprovalRequiredMessage(messages);
    if (approval) return nextApprovalStatusText({ pending_approval: approval.metadata?.pending_approval });
    if (summaryNotice?.tone === 'pending') return summaryNotice.text;
    const latest = latestVisibleActivity(messages);
    const countLabel = processingCount > 1 ? `${processingCount} 项 · ` : '';
    return `${countLabel}${compactStatusText(activityLabel(latest) || '处理中...')}`;
  }
  if (summaryNotice?.tone === 'failed') return summaryNotice.text;
  if (failed) return `处理失败：${compactStatusText(messageErrorText(failed))}`;
  return '就绪';
}

function latestApprovalRequiredMessage(messages: YachiyoChatMessage[]) {
  const approvals = approvalRequiredMessages(messages);
  return approvals[approvals.length - 1] || null;
}
