import { useState } from 'react';

import { openAppView } from '../../../lib/bridge';
import { runtimeToolDisplayLabelOrName } from '../../runtime-shared/approval';
import { runtimeTimelineEventLabel } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { yachiyoTaskStudioGroupRunId, yachiyoTaskStudioRunId, yachiyoTaskStudioUrl } from '../taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot, PublicRunEvent } from '../types';

type LauncherTaskMode = 'bubble' | 'live2d';
type LauncherTaskApprovalAction = 'approve' | 'reject';
type LauncherTaskAction = LauncherTaskApprovalAction | 'cancel';
type LauncherTaskApprovalHandler = (
  task: AgentTaskSnapshot,
  approval: ApprovalCardSnapshot,
) => unknown | Promise<unknown>;
type LauncherTaskCancelHandler = (task: AgentTaskSnapshot) => unknown | Promise<unknown>;

export type LauncherAgentTask = AgentTaskSnapshot | null | undefined;

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

export function launcherAgentTaskChatParams(task: LauncherAgentTask): Record<string, string> | undefined {
  if (!task) return undefined;
  const params: Record<string, string> = {};
  const sessionId = String(task.conversation_id || '').trim();
  const taskId = String(task.task_id || '').trim();
  if (sessionId) params.session_id = sessionId;
  if (taskId) params.task_id = taskId;
  return Object.keys(params).length ? params : undefined;
}

export function LauncherAgentTaskLight({
  mode,
  onApproveApproval,
  onCancelTask,
  onRejectApproval,
  task,
  testIdPrefix = `${mode}-launcher`,
  variant = 'launcher',
}: {
  mode: LauncherTaskMode;
  onApproveApproval?: LauncherTaskApprovalHandler;
  onCancelTask?: LauncherTaskCancelHandler;
  onRejectApproval?: LauncherTaskApprovalHandler;
  task: LauncherAgentTask;
  testIdPrefix?: string;
  variant?: 'launcher' | 'panel';
}) {
  const [taskAction, setTaskAction] = useState<LauncherTaskAction | ''>('');
  if (!task) return null;
  const currentTask = task;
  const runId = yachiyoTaskStudioRunId(currentTask);
  const groupRunId = yachiyoTaskStudioGroupRunId(currentTask);
  const studioUrl = yachiyoTaskStudioUrl(currentTask);
  const status = String(currentTask.status || '');
  const approval = launcherAgentTaskPendingApproval(currentTask);
  const needsAction = Boolean(currentTask.needs_user_action || approval);
  const taskTitle = launcherAgentTaskTitle(currentTask);
  const detail = launcherAgentTaskDetail(currentTask);
  const canHandleApproval = Boolean(approval && (onApproveApproval || onRejectApproval));
  const canCancel = Boolean(onCancelTask && launcherAgentTaskCanCancel(currentTask));
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
      data-testid={`${testIdPrefix}-agent-task-light`}
    >
      <button
        type="button"
        className="launcher-agent-task-main"
        data-testid={`${testIdPrefix}-agent-task-open-chat`}
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
          <small data-testid={`${testIdPrefix}-agent-task-detail`}>{detail}</small>
        ) : null}
        {needsAction ? <em>待处理</em> : null}
      </button>
      {runId && studioUrl ? (
        <a
          href={studioUrl}
          className="launcher-agent-task-studio"
          data-run-id={runId}
          data-studio-url={studioUrl}
          data-testid={`${testIdPrefix}-agent-task-open-studio`}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void openAppView('agents', {
              run: runId,
              ...(groupRunId ? { group_run: groupRunId } : {}),
            });
          }}
          title="在 Agent Studio 中查看"
        >
          Agent Studio
        </a>
      ) : null}
      {canHandleApproval || canCancel ? (
        <div className="launcher-agent-task-actions" data-testid={`${testIdPrefix}-agent-task-approval-actions`}>
          {canHandleApproval ? (
            <>
              <button
                type="button"
                className="launcher-agent-task-action approve"
                data-testid={`${testIdPrefix}-agent-task-approve`}
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
                data-testid={`${testIdPrefix}-agent-task-reject`}
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
              data-testid={`${testIdPrefix}-agent-task-cancel`}
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
