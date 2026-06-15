import { openAppView } from '../../../lib/bridge';
import { yachiyoTaskRunId } from '../taskSnapshots';
import type { AgentTaskSnapshot } from '../types';

type LauncherTaskMode = 'bubble' | 'live2d';

export type LauncherAgentTask = AgentTaskSnapshot | null | undefined;

export function launcherAgentTaskSummary(task: LauncherAgentTask) {
  if (!task) return '';
  const label = launcherAgentTaskStatusLabel(task.status || '');
  const title = String(task.title || '').trim();
  return title ? `${label} · ${title}` : label;
}

export function launcherAgentTaskDetail(task: LauncherAgentTask) {
  if (!task) return '';
  const approval = task.pending_approvals?.find((item) => item.tool_name || item.title);
  if (approval) return `审批 · ${approval.tool_name || approval.title}`;
  const step = String(task.current_step || task.progress_text || '').trim();
  if (step) return step;
  const event = task.recent_events?.find((item) => item.title || item.detail || item.event_type);
  if (event) return String(event.title || event.detail || event.event_type || '').trim();
  const artifact = task.artifacts?.find((item) => item.title || item.path || item.kind);
  if (artifact) return `产物 · ${artifact.title || artifact.path || artifact.kind}`;
  return String(task.summary || '').trim();
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
  task,
  testIdPrefix = `${mode}-launcher`,
  variant = 'launcher',
}: {
  mode: LauncherTaskMode;
  task: LauncherAgentTask;
  testIdPrefix?: string;
  variant?: 'launcher' | 'panel';
}) {
  if (!task) return null;
  const runId = yachiyoTaskRunId(task);
  const status = String(task.status || '');
  const needsAction = Boolean(task.needs_user_action || task.pending_approvals?.length);
  const detail = launcherAgentTaskDetail(task);
  return (
    <div
      className={`launcher-agent-task-light ${launcherAgentTaskTone(status)} ${variant === 'panel' ? 'is-panel' : ''}`}
      data-run-id={runId}
      data-task-id={task.task_id}
      data-testid={`${testIdPrefix}-agent-task-light`}
    >
      <button
        type="button"
        className="launcher-agent-task-main"
        data-testid={`${testIdPrefix}-agent-task-open-chat`}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void openAppView('chat', launcherAgentTaskChatParams(task));
        }}
        title="在 Chat 中查看任务"
      >
        <span>{launcherAgentTaskStatusLabel(status)}</span>
        <strong>{task.title || task.task_id}</strong>
        {detail ? (
          <small data-testid={`${testIdPrefix}-agent-task-detail`}>{detail}</small>
        ) : null}
        {needsAction ? <em>待处理</em> : null}
      </button>
      {runId ? (
        <button
          type="button"
          className="launcher-agent-task-studio"
          data-run-id={runId}
          data-testid={`${testIdPrefix}-agent-task-open-studio`}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void openAppView('agents', { run: runId });
          }}
          title="在 Agent Studio 中查看"
        >
          Studio
        </button>
      ) : null}
    </div>
  );
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
