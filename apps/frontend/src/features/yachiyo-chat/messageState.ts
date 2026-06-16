import {
  approvalRequiredMessages,
  nextApprovalStatusText,
} from './approvalItems';
import { runtimeToolDisplayLabelOrName } from '../runtime-shared/approval';
import type {
  ChatActivityEvent,
  ChatMessage,
  ChatMessageMetadata,
} from './types';

export type YachiyoChatActivityEvent = ChatActivityEvent;
export type YachiyoChatMessageMetadata = ChatMessageMetadata;
export type YachiyoChatMessage = ChatMessage;

export type GroupAgentSummaryNotice = {
  tone: 'pending' | 'failed' | 'completed';
  text: string;
};

export function metadataListAttribute(value: unknown): string {
  if (!Array.isArray(value)) return '';
  return value.map((item) => String(item || '').trim()).filter(Boolean).join(',');
}

export function messageText(message: YachiyoChatMessage) {
  return String(message.content || message.text || '');
}

export function messageErrorText(message: YachiyoChatMessage) {
  return String(
    message.error || message.content || message.text || '任务执行失败',
  ).trim();
}

export function groupAgentSummaryNotice(message: YachiyoChatMessage): GroupAgentSummaryNotice | null {
  const metadata = message.metadata || {};
  const status = String(metadata.group_agent_summary_status || '').trim();
  const subject = groupAgentSummarySubject(metadata);
  if (status === 'cancelled') {
    return { tone: 'failed', text: `主模型整理${subject}已取消。` };
  }
  if (status === 'failed') {
    const error = String(metadata.group_agent_summary_error || '').trim();
    return {
      tone: 'failed',
      text: error ? `主模型整理${subject}失败：${error}` : `主模型整理${subject}失败，请查看后续消息或重试。`,
    };
  }
  if (status === 'completed') {
    return { tone: 'completed', text: `主模型已整理${subject}。` };
  }
  if (metadata.group_agent_summary_pending) {
    return { tone: 'pending', text: `等待主模型整理${subject}...` };
  }
  return null;
}

export function groupFollowupNotice(message: YachiyoChatMessage): string {
  if (message.role !== 'user') return '';
  const metadata = message.metadata || {};
  const taskCount = Array.isArray(metadata.group_followup_for_task_ids)
    ? metadata.group_followup_for_task_ids.filter(Boolean).length
    : 0;
  const agentMessageCount = Array.isArray(metadata.group_followup_for_agent_message_ids)
    ? metadata.group_followup_for_agent_message_ids.filter(Boolean).length
    : 0;
  if (!taskCount && !agentMessageCount) return '';
  if (agentMessageCount && !taskCount) return '已作为当前 Agent 汇总补充';
  return '已作为当前群组任务补充';
}

export function latestGroupAgentSummaryNotice(messages: YachiyoChatMessage[]) {
  let pendingNotice: { tone: 'pending' | 'failed'; text: string } | null = null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const notice = groupAgentSummaryNotice(messages[index]);
    if (!notice) continue;
    if (notice.tone === 'completed') continue;
    if (notice.tone === 'failed') return notice;
    if (notice.tone === 'pending') pendingNotice ||= { tone: 'pending', text: notice.text };
  }
  return pendingNotice;
}

export function normalizeRunStatus(status?: unknown) {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

export function runnableResultRunId(result: { run_id?: string; agent_run_id?: string; workflow_run_id?: string }) {
  return String(result.run_id || result.agent_run_id || result.workflow_run_id || '').trim();
}

export function runnableResultStatus(result: { run_status?: string; status?: string }) {
  return normalizeRunStatus(result.run_status || result.status || '');
}

export function runnableResultLabel(result: { workflow_run_id?: string }) {
  return result.workflow_run_id ? 'Workflow' : 'Agent';
}

export function messageRunStatus(message?: YachiyoChatMessage | null) {
  return normalizeRunStatus(message?.metadata?.run_status || message?.metadata?.workflow_status || '');
}

export function messageRunId(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.run_id || message?.metadata?.workflow_run_id || '').trim();
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

export function messageArtifactCount(message?: YachiyoChatMessage | null) {
  return Number(message?.metadata?.run_artifact_count || 0);
}

export function messageArtifactTitle(message?: YachiyoChatMessage | null) {
  return message?.metadata?.run_artifacts?.map((artifact) => artifact.path).filter(Boolean).join('\n') || '查看运行产物';
}

export function groupAgentSummaryTaskId(message?: YachiyoChatMessage | null) {
  return String(message?.metadata?.group_agent_summary_task_id || '').trim();
}

export function groupAgentSummaryStatus(message?: YachiyoChatMessage | null) {
  const metadata = message?.metadata || {};
  return String(metadata.group_agent_summary_status || (metadata.group_agent_summary_pending ? 'pending' : '')).trim();
}

export function groupAgentSummaryRunGroupId(message?: YachiyoChatMessage | null) {
  const metadata = message?.metadata || {};
  return String(metadata.group_dispatch_run_group_id || metadata.run_group_id || '').trim();
}

export function groupFollowupTaskIdsAttribute(message?: YachiyoChatMessage | null) {
  return metadataListAttribute(message?.metadata?.group_followup_for_task_ids);
}

export function groupFollowupAgentMessageIdsAttribute(message?: YachiyoChatMessage | null) {
  return metadataListAttribute(message?.metadata?.group_followup_for_agent_message_ids);
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

function groupAgentSummarySubject(metadata: YachiyoChatMessageMetadata) {
  const hasGroupDispatch = (
    metadata.group_dispatch_count !== undefined
    || metadata.group_dispatch_run_group_id
    || Array.isArray(metadata.group_dispatch_skipped)
  );
  return hasGroupDispatch ? '这一轮群组任务' : '这条 Agent 结果';
}
