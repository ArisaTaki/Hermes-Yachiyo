import type { AgentTaskSnapshot } from './types';

export const LAUNCHER_MAIN_AGENT_ID = 'builtin:yachiyo-main';
const LAUNCHER_TASK_ACTION_POLL_DELAYS_MS = [300, 800, 1500, 2500];

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
  const preferredActiveTask = launcherPreferredActiveTask(snapshots);
  if (preferredActiveTask) return preferredActiveTask;
  const fallbackTaskId = String(fallback?.task_id || '').trim();
  const matchingFallbackTask = fallbackTaskId
    ? snapshots.find((task) => String(task.task_id || '').trim() === fallbackTaskId)
    : null;
  if (matchingFallbackTask) return matchingFallbackTask;
  const fallbackConversationId = String(fallback?.conversation_id || '').trim();
  const matchingConversationTask = fallbackConversationId
    ? snapshots.find((task) => String(task.conversation_id || '').trim() === fallbackConversationId)
    : null;
  return matchingConversationTask || fallback || snapshots[0] || null;
}

export function launcherAgentTaskIsActive(task: AgentTaskSnapshot | null | undefined) {
  if (!task) return false;
  const status = String(task.status || '').toLowerCase();
  if (['completed', 'success', 'succeeded', 'failed', 'cancelled', 'canceled'].includes(status)) return false;
  if (task.needs_user_action || task.pending_approvals?.length) return true;
  return status === 'queued' || status === 'running' || status === 'waiting_approval';
}

export async function refreshLauncherAgentTaskAfterAction({
  loadTask,
  refresh,
  rememberTask,
  shouldContinue = () => true,
  task,
}: {
  loadTask: (taskId: string) => Promise<AgentTaskSnapshot>;
  refresh: () => Promise<unknown>;
  rememberTask: (task: AgentTaskSnapshot) => void;
  shouldContinue?: () => boolean;
  task: AgentTaskSnapshot;
}) {
  const taskId = String(task.task_id || '').trim();
  let latestTask = task;
  if (shouldContinue()) rememberTask(latestTask);
  await refresh();
  if (!taskId || !launcherAgentTaskIsActive(latestTask)) return latestTask;

  for (const delayMs of LAUNCHER_TASK_ACTION_POLL_DELAYS_MS) {
    await waitForLauncherTaskActionPoll(delayMs);
    if (!shouldContinue()) return latestTask;
    try {
      await refresh();
      latestTask = await loadTask(taskId);
      if (shouldContinue()) rememberTask(latestTask);
    } catch {
      return latestTask;
    }
    if (!launcherAgentTaskIsActive(latestTask)) return latestTask;
  }
  return latestTask;
}

export function launcherPreferredActiveTask(tasks: AgentTaskSnapshot[]) {
  const activeTasks = tasks.filter(launcherAgentTaskIsActive);
  if (!activeTasks.length) return null;
  return [...activeTasks].sort((left, right) => (
    launcherAgentTaskPriority(left) - launcherAgentTaskPriority(right)
      || launcherAgentTaskUpdatedAt(right) - launcherAgentTaskUpdatedAt(left)
  ))[0] || null;
}

function launcherAgentTaskPriority(task: AgentTaskSnapshot) {
  if (task.needs_user_action || task.pending_approvals?.length || task.status === 'waiting_approval') return 0;
  if (task.status === 'running') return 1;
  if (task.status === 'queued') return 2;
  return 3;
}

function launcherAgentTaskUpdatedAt(task: AgentTaskSnapshot) {
  const timestamp = Date.parse(String(task.updated_at || task.created_at || ''));
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function waitForLauncherTaskActionPoll(delayMs: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
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
