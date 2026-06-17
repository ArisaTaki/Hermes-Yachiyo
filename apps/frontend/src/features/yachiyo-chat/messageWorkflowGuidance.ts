import type { ChatMessage } from './types';

export type MessageWorkflowStudioAction = {
  label: string;
  runnableId: string;
  suggestedGoal: string;
};

export function messageWorkflowStudioAction(message?: ChatMessage | null): MessageWorkflowStudioAction | null {
  const metadata = message?.metadata || {};
  if (metadata.guidance_type !== 'workflow_chat_entry_disabled') return null;
  const runnableId = String(metadata.runnable_id || '').trim();
  return {
    label: runnableId ? '在 Agent Studio 中运行' : '打开 Workflow Studio',
    runnableId,
    suggestedGoal: String(metadata.suggested_goal || '').trim(),
  };
}
