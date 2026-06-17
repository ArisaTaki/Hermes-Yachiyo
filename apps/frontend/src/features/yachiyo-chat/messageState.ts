import {
  approvalRequiredMessages,
  nextApprovalStatusText,
} from './approvalItems';
import { participantDisplayName } from './sessionState';
import { latestGroupAgentSummaryNotice } from './messageGroups';
import { runtimeToolDisplayLabelOrName } from '../runtime-shared/approval';
import type { ChatActivityEvent, ChatMessage } from './types';

export type YachiyoChatActivityEvent = ChatActivityEvent;
export type YachiyoChatMessage = ChatMessage;

export function messageText(message: YachiyoChatMessage) {
  return String(message.content || message.text || '');
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
  const label = String(event.title || event.detail || '').trim();
  if (label) return runtimeToolDisplayLabelOrName(label);
  return runtimeToolDisplayLabelOrName(String(event.tool_name || '').trim());
}

export function activityRunId(event?: YachiyoChatActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
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
