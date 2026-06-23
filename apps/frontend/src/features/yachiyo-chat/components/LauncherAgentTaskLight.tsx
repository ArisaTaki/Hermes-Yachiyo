import { useState } from 'react';

import { openAppView } from '../../../lib/bridge';
import { runtimeToolDisplayLabelOrName } from '../../runtime-shared/approval';
import { runtimeTimelineEventLabel } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { taskPermissionRecoveryFromTaskFacts, type TaskPermissionRecoveryAction } from './AgentTaskCard';
import { yachiyoTaskStudioTarget, yachiyoTaskStudioUrl } from '../taskSnapshots';
import type { AgentTaskLightSnapshot, AgentTaskSnapshot, ApprovalCardSnapshot, PublicRunEvent } from '../types';

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
  openChat: string;
  openStudio: string;
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
    openChat: 'bubble-launcher-agent-task-open-chat',
    openStudio: 'bubble-launcher-agent-task-open-studio',
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
    openChat: 'live2d-launcher-agent-task-open-chat',
    openStudio: 'live2d-launcher-agent-task-open-studio',
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
  const approval = task.pending_approvals?.find((item) => item.tool_name || item.title);
  if (approval) {
    const approvalTitle = approval.tool_name
      ? runtimeToolDisplayLabelOrName(approval.tool_name)
      : String(approval.title || '').trim();
    return `审批 · ${approvalTitle || '人工确认'}`;
  }
  const step = String(task.current_step || task.progress_text || '').trim();
  if (step) return step;
  const toolCall = task.tool_calls?.find((item) => item.tool_name);
  if (toolCall) return launcherAgentTaskToolCallLabel(toolCall);
  const event = task.recent_events?.find((item) => item.title || item.detail || item.event_type);
  if (event) return launcherAgentTaskEventLabel(event);
  const artifact = task.artifacts?.find((item) => item.title || item.path || item.kind);
  if (artifact) return `产物 · ${artifact.title || artifact.path || artifact.kind}`;
  return String(task.summary || '').trim();
}

function launcherAgentTaskEventLabel(event: PublicRunEvent) {
  const label = runtimeTimelineEventLabel(event);
  if (label && label !== '运行事件') return label;
  const detail = String(event.detail || '').trim();
  if (detail) return runtimeToolDisplayLabelOrName(detail);
  return label || '运行事件';
}

function launcherAgentTaskToolCallLabel(toolCall: { status?: string; tool_name?: string }) {
  const toolName = String(toolCall.tool_name || '').trim();
  const label = runtimeToolDisplayLabelOrName(toolName || 'tool');
  const status = launcherAgentTaskToolCallStatusLabel(String(toolCall.status || '').trim());
  return status ? `${status} · ${label}` : `执行 · ${label}`;
}

function launcherAgentTaskToolCallStatusLabel(status: string) {
  if (status === 'completed') return '已执行';
  if (status === 'waiting_approval' || status === 'approval_required') return '待审批';
  if (status === 'blocked') return '被占用';
  if (status === 'failed') return '失败';
  if (status === 'running') return '执行中';
  if (status === 'queued' || status === 'planned') return '准备执行';
  if (status === 'unavailable') return '不可用';
  return '';
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
  const approval = launcherAgentTaskPendingApproval(task);
  return {
    task_id: task.task_id,
    conversation_id: task.conversation_id,
    title: launcherAgentTaskTitle(task),
    status: task.status || 'running',
    detail: launcherAgentTaskDetail(task) || null,
    needs_user_action: Boolean(task.needs_user_action || approval),
    pending_approval: approval,
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
    openChat: `${testIdPrefix}-agent-task-open-chat`,
    openStudio: `${testIdPrefix}-agent-task-open-studio`,
    recovery: `${testIdPrefix}-agent-task-run-recovery-action`,
    reject: `${testIdPrefix}-agent-task-reject`,
  };
}

export function LauncherAgentTaskLight({
  mode,
  onApproveApproval,
  onCancelTask,
  onRejectApproval,
  onRunRecoveryAction,
  task,
  testIdPrefix = `${mode}-launcher`,
  variant = 'launcher',
}: {
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
  if (!task) return null;
  const currentTask = task;
  const lightTask = launcherAgentTaskLightSnapshot(currentTask);
  if (!lightTask) return null;
  const studioTarget = yachiyoTaskStudioTarget(currentTask, lightTask.open_in_studio_url || '');
  const { runId, studioUrl } = studioTarget;
  const studioParams = studioTarget.routeParams;
  const status = String(lightTask.status || currentTask.status || '');
  const approval = lightTask.pending_approval || launcherAgentTaskPendingApproval(currentTask);
  const needsAction = Boolean(lightTask.needs_user_action || approval);
  const taskTitle = launcherAgentTaskTitle(currentTask);
  const permissionRecovery = taskPermissionRecoveryFromTaskFacts(
    currentTask.recent_events,
    currentTask.tool_calls,
  );
  const detail = permissionRecovery
    ? `需要权限 · ${permissionRecovery.labels.join('、')}`
    : lightTask.detail || launcherAgentTaskDetail(currentTask);
  const canHandleApproval = Boolean(approval && (onApproveApproval || onRejectApproval));
  const canCancel = Boolean(onCancelTask && launcherAgentTaskCanCancel(currentTask));
  const testIds = launcherAgentTaskTestIds(mode, testIdPrefix);
  const primaryRecoveryAction = permissionRecovery?.actions[0] || null;
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
      className={`launcher-agent-task-light ${launcherAgentTaskTone(status)} ${variant === 'panel' ? 'is-panel' : ''}`}
      data-run-id={runId}
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
        <span>{launcherAgentTaskStatusLabel(status)}</span>
        <strong>{taskTitle}</strong>
        {detail ? (
          <small data-testid={testIds.detail}>{detail}</small>
        ) : null}
        {needsAction ? <em>待处理</em> : null}
      </button>
      {runId && studioUrl && studioParams ? (
        <a
          href={studioUrl}
          className="launcher-agent-task-studio"
          data-run-id={runId}
          data-studio-url={studioUrl}
          data-testid={testIds.openStudio}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void openAppView('agents', studioParams);
          }}
          title="在 Agent Studio 中查看"
        >
          Agent Studio
        </a>
      ) : null}
      {permissionRecovery ? (
        <button
          type="button"
          className="launcher-agent-task-diagnostics"
          data-desktop-tools={permissionRecovery.tools.join(',')}
          data-permission-targets={permissionRecovery.targets.join(',')}
          data-testid={testIds.diagnostics}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void openAppView('diagnostics', {
              command: 'native doctor',
              desktop_tools: permissionRecovery.tools.join(','),
              permission_targets: permissionRecovery.targets.join(','),
              return_to: mode,
            });
          }}
          title={`打开诊断：${permissionRecovery.labels.join('、')}`}
        >
          权限
        </button>
      ) : null}
      {primaryRecoveryAction ? (
        <button
          type="button"
          className="launcher-agent-task-recovery"
          data-permission-target={primaryRecoveryAction.permission_target}
          data-recovery-tool={primaryRecoveryAction.tool}
          data-testid={testIds.recovery}
          disabled={Boolean(taskAction) || !onRunRecoveryAction}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void onRunRecoveryAction?.(currentTask, primaryRecoveryAction);
          }}
          title={primaryRecoveryAction.prompt}
        >
          恢复
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
                title="批准任务审批"
              >
                {taskAction === 'approve' ? '处理中' : '批准'}
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
                title="拒绝任务审批"
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
              title="取消任务"
            >
              {taskAction === 'cancel' ? '取消中' : '取消'}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function launcherAgentTaskPendingApproval(task: AgentTaskSnapshot): ApprovalCardSnapshot | null {
  return task.pending_approvals?.find((approval) => !approval.status || approval.status === 'pending')
    || task.pending_approvals?.[0]
    || null;
}

function launcherAgentTaskCanCancel(task: AgentTaskSnapshot): boolean {
  return ['queued', 'running', 'waiting_approval'].includes(String(task.status || ''));
}

function launcherAgentTaskStatusLabel(status: string) {
  if (status === 'waiting_approval') return '等待审批';
  if (status === 'running' || status === 'queued') return 'Agent 运行中';
  if (status === 'completed') return 'Agent 已完成';
  if (status === 'failed') return 'Agent 失败';
  if (status === 'cancelled') return 'Agent 已取消';
  return 'Agent Task';
}

function launcherAgentTaskTone(status: string) {
  if (status === 'waiting_approval') return 'approval';
  if (status === 'running' || status === 'queued') return 'running';
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  if (status === 'cancelled') return 'cancelled';
  return 'neutral';
}
