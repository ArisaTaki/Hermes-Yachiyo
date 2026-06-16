import type { AgentTaskSnapshot } from './types';

export type LauncherTaskMode = 'bubble' | 'live2d';

type LauncherTaskPayloadContext = {
  chat?: {
    agent_task?: AgentTaskSnapshot | null;
    session_id?: string | null;
  } | null;
  proactive?: {
    has_attention?: boolean;
    session_id?: string | null;
  } | null;
} | null;

export function launcherAgentTaskFromPublicTasks(
  tasks: AgentTaskSnapshot[],
  fallback: AgentTaskSnapshot | null,
): AgentTaskSnapshot | null {
  const snapshots = Array.isArray(tasks) ? tasks.filter(Boolean) : [];
  if (!snapshots.length) return fallback;
  const fallbackTaskId = String(fallback?.task_id || '').trim();
  const matchingFallbackTask = fallbackTaskId
    ? snapshots.find((task) => String(task.task_id || '').trim() === fallbackTaskId)
    : null;
  if (matchingFallbackTask) return matchingFallbackTask;
  const activeTask = snapshots.find(launcherAgentTaskIsActive);
  if (activeTask) return activeTask;
  const fallbackConversationId = String(fallback?.conversation_id || '').trim();
  const matchingConversationTask = fallbackConversationId
    ? snapshots.find((task) => String(task.conversation_id || '').trim() === fallbackConversationId)
    : null;
  return matchingConversationTask || fallback || snapshots[0] || null;
}

export function launcherAgentTaskIsActive(task: AgentTaskSnapshot | null | undefined) {
  if (!task) return false;
  if (task.needs_user_action || task.pending_approvals?.length) return true;
  return task.status === 'queued' || task.status === 'running' || task.status === 'waiting_approval';
}

export function launcherTaskConversationId(mode: LauncherTaskMode, data: LauncherTaskPayloadContext) {
  const sessionId = mode === 'live2d' && data?.proactive?.has_attention
    ? data?.proactive?.session_id
    : data?.chat?.session_id;
  return String(sessionId || '').trim() || null;
}

export function launcherTaskTitle(prompt: string) {
  const text = prompt.trim().replace(/\s+/g, ' ');
  if (!text) return 'Launcher Task';
  return text.length > 40 ? `${text.slice(0, 39)}...` : text;
}
