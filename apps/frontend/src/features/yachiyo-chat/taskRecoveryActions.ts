import {
  assertRuntimeRecoveryActionApprovalReady,
  desktopProviderSessionRecoveryStatusMessage,
  desktopProviderSessionStartRequestFromAction,
  runtimeRecoveryActionIsDesktopProviderSessionStart,
  type DesktopProviderSessionSnapshot,
} from '../runtime-shared/desktopProviderSessionRecovery';
import {
  runtimeToolRecoveryActionsFromRecords,
  runtimeToolRecoveryActionRunStartRequest,
  runtimeToolRecoveryActionTaskStart,
  runtimeToolRecoveryMissingRequiredFields,
  type RuntimeToolRecoveryAction,
  type RuntimeToolRecoveryActionTaskStart,
} from '../runtime-shared/toolRecoveryActions';
import {
  startYachiyoDesktopProviderSession,
  startYachiyoTaskReplanRecoveryAction,
  type YachiyoTaskNextReplanContinuationRequest,
} from './api';
import type { AgentTaskSnapshot } from './types';

export type YachiyoTaskReplanRecoverySnapshot = NonNullable<AgentTaskSnapshot['replan_recoveries']>[number];

export type YachiyoTaskReplanRecoveryActionItem = {
  action: RuntimeToolRecoveryAction;
  index: number;
  recovery: YachiyoTaskReplanRecoverySnapshot;
};

export type YachiyoTaskRecoveryActionStartResult = {
  fallbackResult?: unknown;
  mode: 'desktop_provider_session' | 'none' | 'replan' | 'task';
  prompt: string;
  providerSession?: DesktopProviderSessionSnapshot;
  replanAttempted: boolean;
  statusMessage?: string;
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

export type YachiyoTaskNextAutoReplanContinuation = {
  action: RuntimeToolRecoveryAction;
  key: string;
  recovery: YachiyoTaskReplanRecoverySnapshot;
  request: YachiyoTaskNextReplanContinuationRequest;
};

export function yachiyoTaskReplanRecoveryActions(
  recovery: YachiyoTaskReplanRecoverySnapshot,
): RuntimeToolRecoveryAction[] {
  return runtimeToolRecoveryActionsFromRecords([
    recovery as unknown as Record<string, unknown>,
  ]);
}

export function yachiyoTaskReplanRecoveryActionItems(
  task: AgentTaskSnapshot,
  limit = 5,
): YachiyoTaskReplanRecoveryActionItem[] {
  const items = (task.replan_recoveries || []).flatMap((recovery) => (
    yachiyoTaskReplanRecoveryActions(recovery)
      .map((action, index) => ({ action, index, recovery }))
  ));
  return Number.isFinite(limit) && limit >= 0 ? items.slice(0, limit) : items;
}

export function yachiyoTaskPrimaryReplanRecoveryAction(
  task: AgentTaskSnapshot,
): YachiyoTaskReplanRecoveryActionItem | null {
  return yachiyoTaskReplanRecoveryActionItems(task, 1)[0] || null;
}

export function yachiyoTaskNextAutoReplanContinuation(
  task: AgentTaskSnapshot,
  conversationId?: string | null,
): YachiyoTaskNextAutoReplanContinuation | null {
  const taskId = String(task.task_id || '').trim();
  if (!taskId) return null;
  const recoveries = [...(task.replan_recoveries || [])].reverse();
  for (const recovery of recoveries) {
    const requestId = String(recovery.request_id || '').trim();
    if (!requestId || replanRecoveryIsResolved(recovery)) continue;
    const actions = yachiyoTaskReplanRecoveryActions(recovery);
    for (const action of actions) {
      const actionId = String(action.action_id || '').trim();
      if (!actionId || !action.auto_start_eligible) continue;
      if (action.approval_required === true) continue;
      if (action.auto_start_blockers?.length) continue;
      if (runtimeToolRecoveryMissingRequiredFields(action).length) continue;
      const updatedAt = String(recovery.updated_at || recovery.created_at || '').trim();
      return {
        action,
        key: [
          taskId,
          requestId,
          actionId,
          action.tool || '',
          updatedAt,
        ].join(':'),
        recovery,
        request: {
          request_id: requestId,
          action_id: actionId,
          title: action.label || action.prompt || action.tool,
          continue_to_model: true,
          conversation_id: conversationId || task.conversation_id || null,
          metadata: {
            source: 'yachiyo_chat_replan_auto_continuation_frontend',
            source_task_id: taskId,
            replan_auto_start_reason: action.auto_start_reason || '',
            replan_auto_trigger: 'task_snapshot',
          },
        },
      };
    }
  }
  return null;
}

export function yachiyoTaskRuntimeExecutionRetryActions(
  task: AgentTaskSnapshot,
  limit = 3,
): RuntimeToolRecoveryAction[] {
  const envelope = task.runtime_execution_envelope;
  const requests = envelope?.requests || [];
  if (!requests.length) return [];
  const allowPlannedRetries = (
    task.task_progress?.needs_replan === true
    || Number(task.task_progress?.failed_verification_count || 0) > 0
  );
  const actions = requests
    .map((request) => runtimeExecutionRequestRetryAction(request, allowPlannedRetries))
    .filter((action): action is RuntimeToolRecoveryAction => Boolean(action));
  const deduped = dedupeRuntimeRecoveryActions(actions);
  return Number.isFinite(limit) && limit >= 0 ? deduped.slice(0, limit) : deduped;
}

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
  if (runtimeRecoveryActionIsDesktopProviderSessionStart(action)) {
    assertRuntimeRecoveryActionApprovalReady(action);
    const providerSession = await startYachiyoDesktopProviderSession(
      desktopProviderSessionStartRequestFromAction(action),
    );
    return {
      mode: 'desktop_provider_session',
      prompt: action.prompt || action.label || action.tool,
      providerSession,
      replanAttempted: false,
      statusMessage: desktopProviderSessionRecoveryStatusMessage(providerSession),
      task: null,
      title: action.label || action.prompt || action.tool,
    };
  }
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

function replanRecoveryIsResolved(recovery: YachiyoTaskReplanRecoverySnapshot): boolean {
  const status = String(recovery.status || '').trim();
  return status === 'completed' || status === 'resolved' || status === 'cancelled';
}

type RuntimeExecutionRequestForRecovery = NonNullable<
  NonNullable<AgentTaskSnapshot['runtime_execution_envelope']>['requests']
>[number];

function runtimeExecutionRequestRetryAction(
  request: RuntimeExecutionRequestForRecovery,
  allowPlannedRetry: boolean,
): RuntimeToolRecoveryAction | null {
  const retry = objectValue(request.observation_retry);
  if (!Object.keys(retry).length) return null;
  const evidence = objectValue(request.observation_evidence);
  if (!allowPlannedRetry && !runtimeExecutionEvidenceNeedsRetry(evidence)) return null;

  const input = objectValue(retry.input);
  const tool = String(retry.tool || retry.from_tool || request.tool_name || '').trim();
  if (!tool) return null;
  const reason = String(retry.reason || '').trim();
  const target = String(
    retry.target
    || retry.label
    || input.app_name
    || input.query
    || '',
  ).trim();
  const blocker = runtimeExecutionEvidenceBlocker(evidence);
  const permissionTarget = runtimeExecutionPermissionTarget(blocker);
  const label = runtimeExecutionRetryActionLabel(tool, reason, target);
  return {
    action_kind: 'retry_original',
    approval_required: request.approval_required === true,
    input,
    label,
    permission_target: permissionTarget,
    prompt: label,
    recommended_tools: [tool],
    required_retry_fields: [],
    risk_level: String(request.risk_level || '').trim()
      || (request.approval_required === true ? 'medium' : 'low'),
    retry_input: input,
    retry_input_source: 'runtime_execution_envelope',
    retry_prompt: label,
    retry_tool: tool,
    tool,
    verification_targets: uniqueRecords([
      ...recordList(request.verification_targets),
      ...recordList(request.task_verification_targets),
    ]),
  };
}

function runtimeExecutionEvidenceNeedsRetry(evidence: Record<string, unknown>): boolean {
  if (runtimeExecutionEvidenceBlocker(evidence)) return true;
  if (evidence.verification_failed === true) return true;
  if (evidence.foreground_required === true && evidence.foreground_ready === false) return true;
  return false;
}

function runtimeExecutionEvidenceBlocker(evidence: Record<string, unknown>): string {
  const blocker = String(evidence.blocking_condition || '').trim();
  if (blocker) return blocker;
  const conditions = evidence.blocking_conditions;
  if (Array.isArray(conditions)) {
    return String(conditions.find((condition) => String(condition || '').trim()) || '').trim();
  }
  return '';
}

function runtimeExecutionPermissionTarget(blocker: string): string {
  if (blocker === 'foreground_focus_unavailable') return 'foreground_focus';
  if (blocker === 'desktop_session_locked') return 'desktop_session_unlocked';
  if (blocker === 'screen_capture_blank') return 'desktop_screen_visible';
  return blocker || 'runtime_observation_retry';
}

function runtimeExecutionRetryActionLabel(tool: string, reason: string, target: string): string {
  return [
    '重试',
    tool,
    reason,
    target,
  ].filter(Boolean).join(' · ');
}

function dedupeRuntimeRecoveryActions(actions: RuntimeToolRecoveryAction[]): RuntimeToolRecoveryAction[] {
  const byKey = new Map<string, RuntimeToolRecoveryAction>();
  actions.forEach((action) => {
    const key = `${action.tool}:${JSON.stringify(action.input)}:${action.permission_target}`;
    if (!byKey.has(key)) byKey.set(key, action);
  });
  return Array.from(byKey.values());
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => (
    Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  ));
}

function uniqueRecords(records: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  const result: Array<Record<string, unknown>> = [];
  const seen = new Set<string>();
  records.forEach((record) => {
    const key = JSON.stringify(record);
    if (seen.has(key)) return;
    seen.add(key);
    result.push(record);
  });
  return result;
}

function agentTaskSnapshotOrNull(value: unknown): AgentTaskSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const task = value as AgentTaskSnapshot;
  return task.task_id ? task : null;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
