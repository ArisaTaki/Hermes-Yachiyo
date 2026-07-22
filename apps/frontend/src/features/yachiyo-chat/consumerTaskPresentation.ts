import type { RuntimeToolRecoveryAction } from '../runtime-shared/toolRecoveryActions';
import { consumerTaskFailurePresentation } from './consumerFailure';
import {
  taskPermissionRecoveryFromTaskFacts,
  type TaskPermissionRecovery,
} from './taskPermissionRecovery';
import {
  yachiyoTaskPrimaryReplanRecoveryAction,
  yachiyoTaskRuntimeExecutionRetryActions,
  type YachiyoTaskReplanRecoveryActionItem,
} from './taskRecoveryActions';
import type { AgentTaskSnapshot, ApprovalCardSnapshot } from './types';

export type ConsumerTaskPresentationSurface = 'launcher' | 'panel';
export type ConsumerTaskPresentationVisibility = 'hidden' | 'compact' | 'action' | 'summary';
export type ConsumerTaskPresentationState =
  | 'approval'
  | 'permission'
  | 'recovery'
  | 'failed'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'idle';

export type ConsumerTaskPresentation = {
  approval: ApprovalCardSnapshot | null;
  detail: string;
  permissionRecovery: TaskPermissionRecovery | null;
  replanRecoveryAction: YachiyoTaskReplanRecoveryActionItem | null;
  runtimeRetryAction: RuntimeToolRecoveryAction | null;
  state: ConsumerTaskPresentationState;
  statusLabel: string;
  title: string;
  tone: 'approval' | 'running' | 'completed' | 'failed' | 'cancelled' | 'neutral';
  visibility: ConsumerTaskPresentationVisibility;
};

/**
 * Consumer-facing task projection. Runtime facts enter here; tool, planner,
 * policy, and risk identifiers never leave as visible copy.
 */
export function consumerTaskPresentation(
  task: AgentTaskSnapshot,
  surface: ConsumerTaskPresentationSurface = 'launcher',
): ConsumerTaskPresentation {
  const status = String(task.status || '').toLowerCase();
  const terminalSuccess = ['completed', 'success', 'succeeded'].includes(status);
  const cancelled = ['cancelled', 'canceled'].includes(status);
  const running = status === 'queued' || status === 'running';
  const failed = status === 'failed';
  const approval = terminalSuccess || cancelled || failed ? null : pendingTaskApproval(task);
  const permissionRecovery = terminalSuccess || cancelled
    ? null
    : taskPermissionRecoveryFromTaskFacts(task.recent_events, task.tool_calls);
  const explicitlyNeedsAction = !terminalSuccess && !cancelled && Boolean(
    task.needs_user_action
    || approval
    || status === 'waiting_approval'
    || permissionRecovery,
  );
  // A running agent may carry internal replan/retry facts while it is still
  // recovering by itself. Promote those facts only after a failure or when
  // the runtime explicitly asks the user to act.
  const exposeRecovery = failed || explicitlyNeedsAction;
  const replanRecoveryAction = exposeRecovery
    ? yachiyoTaskPrimaryReplanRecoveryAction(task)
    : null;
  const runtimeRetryAction = exposeRecovery
    ? yachiyoTaskRuntimeExecutionRetryActions(task, 1)[0] || null
    : null;
  const hasRecoveryAction = Boolean(replanRecoveryAction || runtimeRetryAction);

  let state: ConsumerTaskPresentationState = 'idle';
  let statusLabel = '任务';
  let title = task.title || '八千代任务';
  let detail = '点击查看任务。';
  let tone: ConsumerTaskPresentation['tone'] = 'neutral';

  if (approval || status === 'waiting_approval') {
    state = 'approval';
    statusLabel = '需要确认';
    title = '需要你的确认';
    detail = approval && !String(approval.approval_id || '').trim()
      ? '确认信息已更新，请打开对话查看。'
      : '确认后会继续当前任务；你也可以拒绝。';
    tone = 'approval';
  } else if (permissionRecovery) {
    state = 'permission';
    statusLabel = '需要授权';
    title = permissionRecovery.kind === 'blocking_condition'
      ? '需要你的处理'
      : '需要系统权限';
    detail = permissionRecovery.kind === 'blocking_condition'
      ? '处理当前桌面状态后即可重试。'
      : '完成系统授权后即可继续。';
    tone = 'approval';
  } else if (hasRecoveryAction) {
    state = 'recovery';
    statusLabel = '可以重试';
    title = '这次还没有完成';
    detail = '上一步没有得到可确认的结果，可以重新尝试。';
    tone = failed ? 'failed' : 'approval';
  } else if (failed) {
    const failure = consumerTaskFailurePresentation({
      ...task,
      needs_user_action: false,
      pending_approvals: [],
    });
    state = 'failed';
    statusLabel = '未完成';
    title = failure.title;
    detail = failure.kind === 'unknown'
      ? '请打开对话查看原因，或稍后重试。'
      : failure.detail;
    tone = 'failed';
  } else if (explicitlyNeedsAction) {
    state = 'approval';
    statusLabel = '需要处理';
    title = '需要你的处理';
    detail = '打开对话查看后即可继续。';
    tone = 'approval';
  } else if (running) {
    state = 'running';
    statusLabel = '处理中';
    title = task.title || '正在处理你的请求';
    detail = '正在处理…';
    tone = 'running';
  } else if (terminalSuccess) {
    state = 'completed';
    statusLabel = '已完成';
    detail = '任务已完成。';
    tone = 'completed';
  } else if (cancelled) {
    state = 'cancelled';
    statusLabel = '已取消';
    detail = '任务已停止。';
    tone = 'cancelled';
  }

  const actionRequired = ['approval', 'permission', 'recovery', 'failed'].includes(state);
  const visibility: ConsumerTaskPresentationVisibility = surface === 'panel'
    ? 'summary'
    : actionRequired
      ? 'action'
      : state === 'running'
        ? 'compact'
        : 'hidden';

  return {
    approval,
    detail,
    permissionRecovery,
    replanRecoveryAction,
    runtimeRetryAction,
    state,
    statusLabel,
    title,
    tone,
    visibility,
  };
}

function pendingTaskApproval(task: AgentTaskSnapshot): ApprovalCardSnapshot | null {
  return task.pending_approvals?.find((approval) => !approval.status || approval.status === 'pending')
    || null;
}
