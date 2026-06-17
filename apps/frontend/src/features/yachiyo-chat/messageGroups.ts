import type { ChatMessage, ChatMessageMetadata } from './types';

export type GroupAgentSummaryNotice = {
  tone: 'pending' | 'failed' | 'completed';
  text: string;
};

export function groupAgentSummaryNotice(message: ChatMessage): GroupAgentSummaryNotice | null {
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

export function groupFollowupNotice(message: ChatMessage): string {
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

export function latestGroupAgentSummaryNotice(messages: ChatMessage[]) {
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

export function groupAgentSummaryTaskId(message?: ChatMessage | null) {
  return String(message?.metadata?.group_agent_summary_task_id || '').trim();
}

export function groupAgentSummaryStatus(message?: ChatMessage | null) {
  const metadata = message?.metadata || {};
  return String(metadata.group_agent_summary_status || (metadata.group_agent_summary_pending ? 'pending' : '')).trim();
}

export function groupAgentSummaryRunGroupId(message?: ChatMessage | null) {
  const metadata = message?.metadata || {};
  return String(metadata.group_dispatch_run_group_id || metadata.run_group_id || '').trim();
}

export function groupFollowupTaskIdsAttribute(message?: ChatMessage | null) {
  return metadataListAttribute(message?.metadata?.group_followup_for_task_ids);
}

export function groupFollowupAgentMessageIdsAttribute(message?: ChatMessage | null) {
  return metadataListAttribute(message?.metadata?.group_followup_for_agent_message_ids);
}

export function isMissingGroupEditRouteError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || '');
  return /\b(?:HTTP 404|404|Not Found)\b/i.test(message);
}

function groupAgentSummarySubject(metadata: ChatMessageMetadata) {
  const hasGroupDispatch = (
    metadata.group_dispatch_count !== undefined
    || metadata.group_dispatch_run_group_id
    || Array.isArray(metadata.group_dispatch_skipped)
  );
  return hasGroupDispatch ? '这一轮群组任务' : '这条 Agent 结果';
}

function metadataListAttribute(value: unknown): string {
  if (!Array.isArray(value)) return '';
  return value.map((item) => String(item || '').trim()).filter(Boolean).join(',');
}
