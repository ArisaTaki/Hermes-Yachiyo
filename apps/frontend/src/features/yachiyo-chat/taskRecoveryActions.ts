import {
  runtimeToolRecoveryActionRunStartRequest,
  runtimeToolRecoveryActionTaskStart,
  type RuntimeToolRecoveryAction,
  type RuntimeToolRecoveryActionTaskStart,
} from '../runtime-shared/toolRecoveryActions';
import { startYachiyoTaskReplanRecoveryAction } from './api';
import type { AgentTaskSnapshot } from './types';

export type YachiyoTaskRecoveryActionStartResult = {
  fallbackResult?: unknown;
  mode: 'none' | 'replan' | 'task';
  prompt: string;
  replanAttempted: boolean;
  task: AgentTaskSnapshot | null;
  title: string;
};

export type StartYachiyoTaskRecoveryActionOptions = {
  action: RuntimeToolRecoveryAction;
  conversationId?: string | null;
  metadata?: Record<string, unknown>;
  onStartedTask?: (task: AgentTaskSnapshot) => void;
  startFallbackTask: (start: RuntimeToolRecoveryActionTaskStart) => Promise<unknown>;
  task: AgentTaskSnapshot;
};

export async function startYachiyoTaskRecoveryAction({
  action,
  conversationId,
  metadata = {},
  onStartedTask,
  startFallbackTask,
  task,
}: StartYachiyoTaskRecoveryActionOptions): Promise<YachiyoTaskRecoveryActionStartResult> {
  const sourceMetadata = {
    source_task_id: task.task_id || '',
    source_task_title: task.title || '',
    ...metadata,
  };
  const fallbackStart = runtimeToolRecoveryActionTaskStart(action, sourceMetadata);
  const prompt = fallbackStart.prompt;
  if (!prompt) {
    return {
      mode: 'none',
      prompt: '',
      replanAttempted: false,
      task: null,
      title: fallbackStart.title,
    };
  }

  const taskId = String(task.task_id || '').trim();
  const replanRequest = runtimeToolRecoveryActionRunStartRequest(
    action,
    action.replan_request_id || '',
    sourceMetadata,
  );
  if (taskId && replanRequest) {
    try {
      const startedTask = await startYachiyoTaskReplanRecoveryAction(taskId, {
        ...replanRequest,
        conversation_id: conversationId || task.conversation_id || null,
      });
      onStartedTask?.(startedTask);
      return {
        mode: 'replan',
        prompt,
        replanAttempted: true,
        task: startedTask,
        title: fallbackStart.title,
      };
    } catch {
      // Older bridges do not expose task-level replan recovery. Fall back to
      // the existing controlled recovery task path.
    }
  }

  const fallbackResult = await startFallbackTask(fallbackStart);
  const fallbackTask = agentTaskSnapshotOrNull(fallbackResult);
  if (fallbackTask) onStartedTask?.(fallbackTask);
  return {
    fallbackResult,
    mode: 'task',
    prompt,
    replanAttempted: Boolean(replanRequest),
    task: fallbackTask,
    title: fallbackStart.title,
  };
}

function agentTaskSnapshotOrNull(value: unknown): AgentTaskSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const task = value as AgentTaskSnapshot;
  return task.task_id ? task : null;
}
