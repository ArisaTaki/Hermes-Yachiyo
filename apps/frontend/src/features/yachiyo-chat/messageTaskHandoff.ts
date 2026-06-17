import type { ChatMessage } from './types';

export function taskHandoffMessageId(messages: ChatMessage[], taskId: string) {
  const clean = String(taskId || '').trim();
  if (!clean) return '';
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message?.id) continue;
    if (messageMatchesTaskHandoff(message, clean)) return message.id;
  }
  return '';
}

export function messageMatchesTaskHandoff(message: ChatMessage, taskId: string) {
  const metadata = message.metadata || {};
  if (String(message.task_id || '').trim() === taskId) return true;
  if (metadataStringValue(metadata.group_agent_summary_task_id) === taskId) return true;
  if (metadataStringValue(metadata.group_agent_summary_for_task_id) === taskId) return true;
  if (metadataStringValue(metadata.delegated_run_source_task_id) === taskId) return true;
  if (metadataListAttribute(metadata.group_followup_for_task_ids).split(',').includes(taskId)) return true;
  return false;
}

function metadataListAttribute(value: unknown): string {
  if (!Array.isArray(value)) return '';
  return value.map((item) => String(item || '').trim()).filter(Boolean).join(',');
}

function metadataStringValue(value: unknown) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}
