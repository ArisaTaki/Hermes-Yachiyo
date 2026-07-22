import { useState, type MutableRefObject } from 'react';

import { openAppView } from '../../../lib/bridge';
import { consumerTaskPresentation } from '../consumerTaskPresentation';
import type { TaskPermissionRecoveryAction } from '../taskPermissionRecovery';
import { yachiyoTaskStudioUrl } from '../taskSnapshots';
import type { AgentTaskLightSnapshot, AgentTaskSnapshot, ApprovalCardSnapshot } from '../types';

type LauncherTaskMode = 'bubble' | 'live2d';
type LauncherTaskApprovalAction = 'approve' | 'reject';
type LauncherTaskAction = LauncherTaskApprovalAction | 'cancel';
type LauncherTaskApprovalHandler = (
  task: AgentTaskSnapshot,
  approval: ApprovalCardSnapshot,
) => unknown | Promise<unknown>;
type LauncherTaskCancelHandler = (task: AgentTaskSnapshot) => unknown | Promise<unknown>;
type LauncherTaskRecoveryHandler = (
  task: AgentTaskSnapshot,
  action: TaskPermissionRecoveryAction,
) => unknown | Promise<unknown>;
type LauncherAgentTaskTestIds = {
  approvalActions: string;
  approve: string;
  cancel: string;
  detail: string;
  diagnostics: string;
  light: string;
  compact: string;
  openChat: string;
  recovery: string;
  reject: string;
};

export type LauncherAgentTask = AgentTaskSnapshot | null | undefined;

const DEFAULT_LAUNCHER_AGENT_TASK_TEST_IDS: Record<LauncherTaskMode, LauncherAgentTaskTestIds> = {
  bubble: {
    approvalActions: 'bubble-launcher-agent-task-approval-actions',
    approve: 'bubble-launcher-agent-task-approve',
    cancel: 'bubble-launcher-agent-task-cancel',
    detail: 'bubble-launcher-agent-task-detail',
    diagnostics: 'bubble-launcher-agent-task-open-diagnostics',
    light: 'bubble-launcher-agent-task-light',
    compact: 'bubble-launcher-agent-task-compact',
    openChat: 'bubble-launcher-agent-task-open-chat',
    recovery: 'bubble-launcher-agent-task-run-recovery-action',
    reject: 'bubble-launcher-agent-task-reject',
  },
  live2d: {
    approvalActions: 'live2d-launcher-agent-task-approval-actions',
    approve: 'live2d-launcher-agent-task-approve',
    cancel: 'live2d-launcher-agent-task-cancel',
    detail: 'live2d-launcher-agent-task-detail',
    diagnostics: 'live2d-launcher-agent-task-open-diagnostics',
    light: 'live2d-launcher-agent-task-light',
    compact: 'live2d-launcher-agent-task-compact',
    openChat: 'live2d-launcher-agent-task-open-chat',
    recovery: 'live2d-launcher-agent-task-run-recovery-action',
    reject: 'live2d-launcher-agent-task-reject',
  },
};

export function launcherAgentTaskSummary(task: LauncherAgentTask) {
  if (!task) return '';
  const label = launcherAgentTaskStatusLabel(task.status || '');
  const title = launcherAgentTaskTitle(task, '');
  return title ? `${label} · ${title}` : label;
}

export function launcherAgentTaskTitle(task: LauncherAgentTask, fallback = '八千代任务') {
  if (!task) return fallback;
  return String(task.title || '').trim() || fallback;
}

export function launcherAgentTaskDetail(task: LauncherAgentTask) {
  if (!task) return '';
  return consumerTaskPresentation(task, 'panel').detail;
}

export function launcherAgentTaskChatParams(task: LauncherAgentTask): Record<string, string> | undefined {
  if (!task) return undefined;
  const params: Record<string, string> = {};
  const sessionId = String(task.conversation_id || '').trim();
  const taskId = String(task.task_id || '').trim();
  if (sessionId) params.session_id = sessionId;
  if (taskId) params.task_id = taskId;
  return Object.keys(params).length ? params : undefined;
}

export function launcherAgentTaskLightSnapshot(task: LauncherAgentTask): AgentTaskLightSnapshot | null {
  if (!task) return null;
  const presentation = consumerTaskPresentation(task, 'panel');
  return {
    task_id: task.task_id,
    conversation_id: task.conversation_id,
    title: launcherAgentTaskTitle(task),
    status: task.status || 'running',
    detail: presentation.detail || null,
    needs_user_action: ['approval', 'permission', 'recovery', 'failed'].includes(presentation.state),
    pending_approval: presentation.approval,
    task_progress: task.task_progress || null,
    runtime_debug: task.runtime_debug || null,
    runtime_execution_envelope: task.runtime_execution_envelope || null,
    open_in_studio_url: yachiyoTaskStudioUrl(task) || null,
    created_at: task.created_at || '',
    updated_at: task.updated_at || '',
  };
}

function launcherAgentTaskTestIds(
  mode: LauncherTaskMode,
  testIdPrefix: string,
): LauncherAgentTaskTestIds {
  if (testIdPrefix === `${mode}-launcher`) return DEFAULT_LAUNCHER_AGENT_TASK_TEST_IDS[mode];
  return {
    approvalActions: `${testIdPrefix}-agent-task-approval-actions`,
    approve: `${testIdPrefix}-agent-task-approve`,
    cancel: `${testIdPrefix}-agent-task-cancel`,
    detail: `${testIdPrefix}-agent-task-detail`,
    diagnostics: `${testIdPrefix}-agent-task-open-diagnostics`,
    light: `${testIdPrefix}-agent-task-light`,
    compact: `${testIdPrefix}-agent-task-compact`,
    openChat: `${testIdPrefix}-agent-task-open-chat`,
    recovery: `${testIdPrefix}-agent-task-run-recovery-action`,
    reject: `${testIdPrefix}-agent-task-reject`,
  };
}

export function LauncherAgentTaskLight({
  containerRef,
  mode,
  onApproveApproval,
  onCancelTask,
  onRejectApproval,
  onRunRecoveryAction,
  task,
  testIdPrefix = `${mode}-launcher`,
  variant = 'launcher',
}: {
  containerRef?: MutableRefObject<HTMLElement | null>;
  mode: LauncherTaskMode;
  onApproveApproval?: LauncherTaskApprovalHandler;
  onCancelTask?: LauncherTaskCancelHandler;
  onRejectApproval?: LauncherTaskApprovalHandler;
  onRunRecoveryAction?: LauncherTaskRecoveryHandler;
  task: LauncherAgentTask;
  testIdPrefix?: string;
  variant?: 'launcher' | 'panel';
}) {
  const [taskAction, setTaskAction] = useState<LauncherTaskAction | ''>('');
  const rememberContainer = (element: HTMLElement | null) => {
    if (containerRef) containerRef.current = element;
  };
  if (!task) return null;
  const currentTask = task;
  const presentation = consumerTaskPresentation(currentTask, variant === 'panel' ? 'panel' : 'launcher');
  const testIds = launcherAgentTaskTestIds(mode, testIdPrefix);
  if (presentation.visibility === 'hidden') return null;
  if (presentation.visibility === 'compact') {
    if (mode === 'bubble') return null;
    return (
      <button
        ref={rememberContainer}
        type="button"
        className="launcher-agent-task-compact"
        data-task-id={currentTask.task_id}
        data-testid={testIds.compact}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void openAppView('chat', launcherAgentTaskChatParams(currentTask));
        }}
        title="在 Chat 中查看任务"
      >
        <span className="launcher-agent-task-compact-dots" aria-hidden="true"><i /><i /><i /></span>
        <span>{presentation.statusLabel}</span>
      </button>
    );
  }

  const approval = presentation.approval;
  const permissionRecovery = presentation.permissionRecovery;
  const replanRecoveryAction = presentation.replanRecoveryAction;
  const runtimeRetryAction = presentation.runtimeRetryAction;
  const staleApproval = Boolean(approval && !String(approval.approval_id || '').trim());
  const canHandleApproval = Boolean(approval && !staleApproval && (onApproveApproval || onRejectApproval));
  const canCancel = Boolean(onCancelTask && launcherAgentTaskCanCancel(currentTask));
  const permissionRecoveryAction = permissionRecovery?.actions[0] || null;
  const primaryReplanRecoveryAction = permissionRecoveryAction ? null : replanRecoveryAction;
  const primaryRuntimeRetryAction = permissionRecoveryAction || primaryReplanRecoveryAction ? null : runtimeRetryAction;
  const primaryRecoveryAction = permissionRecoveryAction || primaryReplanRecoveryAction?.action || primaryRuntimeRetryAction || null;
  async function handleApproval(action: LauncherTaskApprovalAction) {
    if (!approval || taskAction) return;
    const handler = action === 'approve' ? onApproveApproval : onRejectApproval;
    if (!handler) return;
    setTaskAction(action);
    try {
      await handler(currentTask, approval);
    } finally {
      setTaskAction('');
    }
  }
  async function handleCancel() {
    if (!onCancelTask || taskAction || !canCancel) return;
    setTaskAction('cancel');
    try {
      await onCancelTask(currentTask);
    } finally {
      setTaskAction('');
    }
  }
  return (
    <div
      ref={rememberContainer}
      className={`launcher-agent-task-light ${presentation.tone} ${variant === 'panel' ? 'is-panel' : ''}`}
      data-presentation-state={presentation.state}
      data-presentation-visibility={presentation.visibility}
      data-run-id={approval?.run_id || ''}
      data-task-id={currentTask.task_id}
      data-testid={testIds.light}
    >
      <button
        type="button"
        className="launcher-agent-task-main"
        data-testid={testIds.openChat}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void openAppView('chat', launcherAgentTaskChatParams(currentTask));
        }}
        title="在 Chat 中查看任务"
      >
        <span>{presentation.statusLabel}</span>
        <strong>{presentation.title}</strong>
        <small data-testid={testIds.detail}>{presentation.detail}</small>
      </button>
      {staleApproval ? (
        <small className="message-error" data-testid={`${testIdPrefix}-agent-task-approval-stale`}>
          确认信息已更新，请打开对话查看。
        </small>
      ) : null}
      {permissionRecovery ? (
        <button
          type="button"
          className="launcher-agent-task-diagnostics"
          data-blocking-conditions={permissionRecovery.blockingConditions.join(',')}
          data-desktop-tools={permissionRecovery.tools.join(',')}
          data-permission-targets={permissionRecovery.targets.join(',')}
          data-recovery-kind={permissionRecovery.kind}
          data-testid={testIds.diagnostics}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void openAppView('diagnostics', {
              command: 'native doctor',
              ...(permissionRecovery.blockingConditions.length
                ? { blocking_conditions: permissionRecovery.blockingConditions.join(',') }
                : {}),
              desktop_tools: permissionRecovery.tools.join(','),
              permission_targets: permissionRecovery.targets.join(','),
              return_to: mode,
            });
          }}
          title="打开权限设置与解决办法"
        >
          {permissionRecovery.kind === 'blocking_condition' ? '解决' : '授权'}
        </button>
      ) : null}
      {primaryRecoveryAction ? (
        <button
          type="button"
          className="launcher-agent-task-recovery"
          data-permission-target={primaryRecoveryAction.permission_target}
          data-replan-recovery-action-id={primaryReplanRecoveryAction?.action.action_id || ''}
          data-replan-recovery-request-id={primaryReplanRecoveryAction?.recovery.request_id || ''}
          data-replan-recovery-status={primaryReplanRecoveryAction?.recovery.status || ''}
          data-recovery-tool={primaryRecoveryAction.tool}
          data-runtime-retry-action-id={primaryRuntimeRetryAction?.action_id || ''}
          data-runtime-retry-input-source={primaryRuntimeRetryAction?.retry_input_source || ''}
          data-testid={testIds.recovery}
          disabled={Boolean(taskAction) || !onRunRecoveryAction}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void onRunRecoveryAction?.(currentTask, primaryRecoveryAction);
          }}
          title="重试当前任务"
        >
          重试
        </button>
      ) : null}
      {canHandleApproval || canCancel ? (
        <div className="launcher-agent-task-actions" data-testid={testIds.approvalActions}>
          {canHandleApproval ? (
            <>
              <button
                type="button"
                className="launcher-agent-task-action approve"
                data-testid={testIds.approve}
                disabled={Boolean(taskAction) || !onApproveApproval}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  void handleApproval('approve');
                }}
                title="确认并继续任务"
              >
                {taskAction === 'approve' ? '处理中' : '确认继续'}
              </button>
              <button
                type="button"
                className="launcher-agent-task-action reject"
                data-testid={testIds.reject}
                disabled={Boolean(taskAction) || !onRejectApproval}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  void handleApproval('reject');
                }}
                title="拒绝并停止当前操作"
              >
                {taskAction === 'reject' ? '处理中' : '拒绝'}
              </button>
            </>
          ) : null}
          {canCancel ? (
            <button
              type="button"
              className="launcher-agent-task-action cancel"
              data-testid={testIds.cancel}
              disabled={Boolean(taskAction)}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void handleCancel();
              }}
              title="停止任务"
            >
              {taskAction === 'cancel' ? '停止中' : '停止任务'}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function launcherAgentTaskCanCancel(task: AgentTaskSnapshot): boolean {
  return ['queued', 'running', 'waiting_approval'].includes(String(task.status || ''));
}

function launcherAgentTaskStatusLabel(status: string) {
  if (status === 'waiting_approval') return '需要确认';
  if (status === 'running' || status === 'queued') return '处理中';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '未完成';
  if (status === 'cancelled') return '已取消';
  return '任务';
}
