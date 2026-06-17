import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  approveYachiyoTask,
  cancelYachiyoTask,
  listYachiyoTasks,
  rejectYachiyoTask,
} from '../features/yachiyo-chat/api';
import { AgentTaskCard } from '../features/yachiyo-chat/components/AgentTaskCard';
import type { AgentTaskSnapshot, ApprovalCardSnapshot, TaskStatus } from '../features/yachiyo-chat/types';
import { groupRunIdFromStudioUrl, runIdFromStudioUrl } from '../features/runtime-shared/studioLinks';
import { navigateTo } from '../lib/view';

type TaskFilter = 'active' | 'all';

const ACTIVE_TASK_STATUSES: TaskStatus[] = ['queued', 'running', 'waiting_approval'];

export function TasksView() {
  const [tasks, setTasks] = useState<AgentTaskSnapshot[]>([]);
  const [filter, setFilter] = useState<TaskFilter>('active');
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busyActionId, setBusyActionId] = useState('');

  const activeTasks = useMemo(
    () => tasks.filter((task) => ACTIVE_TASK_STATUSES.includes(task.status)),
    [tasks],
  );
  const visibleTasks = filter === 'active' ? activeTasks : tasks;

  const refreshTasks = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const nextTasks = await listYachiyoTasks();
      setTasks(sortTasks(nextTasks));
      setStatus(nextTasks.length ? `已加载 ${nextTasks.length} 个任务。` : '暂无 Agent 任务。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 Agent 任务失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshTasks();
  }, [refreshTasks]);

  function rememberTask(task: AgentTaskSnapshot) {
    setTasks((current) => sortTasks([
      task,
      ...current.filter((item) => item.task_id !== task.task_id),
    ]));
  }

  async function resolveTaskApproval(
    task: AgentTaskSnapshot,
    approval: ApprovalCardSnapshot,
    action: 'approve' | 'reject',
  ) {
    if (!task.task_id || !approval.approval_id || busyActionId) return;
    const actionId = `${task.task_id}:${approval.approval_id}:${action}`;
    setBusyActionId(actionId);
    setStatus(action === 'approve' ? '正在批准任务审批...' : '正在拒绝任务审批...');
    setError('');
    try {
      const nextTask = action === 'approve'
        ? await approveYachiyoTask(task.task_id, approval.approval_id)
        : await rejectYachiyoTask(task.task_id, approval.approval_id, 'Rejected from tasks page');
      rememberTask(nextTask);
      setStatus(taskStatusMessage(nextTask, action));
    } catch (err) {
      setError(err instanceof Error ? err.message : '处理任务审批失败');
    } finally {
      setBusyActionId('');
    }
  }

  async function cancelTask(task: AgentTaskSnapshot) {
    if (!task.task_id || busyActionId) return;
    setBusyActionId(`${task.task_id}:cancel`);
    setStatus('正在取消 Agent 任务...');
    setError('');
    try {
      const nextTask = await cancelYachiyoTask(task.task_id);
      rememberTask(nextTask);
      setStatus(taskStatusMessage(nextTask, 'cancel'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消 Agent 任务失败');
    } finally {
      setBusyActionId('');
    }
  }

  function openTaskInStudio(runId?: string, studioUrl?: string) {
    const targetRunId = String(runId || '').trim() || runIdFromStudioUrl(studioUrl);
    const groupRunId = groupRunIdFromStudioUrl(studioUrl);
    if (!targetRunId) {
      navigateTo('agents');
      return;
    }
    navigateTo('agents', {
      run: targetRunId,
      ...(groupRunId ? { group_run: groupRunId } : {}),
    }, ['tab', 'target', 'goal']);
  }

  return (
    <section className="hy-route-page yachiyo-tasks-page open-chat-shell" data-testid="yachiyo-tasks-page">
      <header className="yachiyo-tasks-header">
        <button type="button" className="page-back-link" onClick={() => navigateTo('main')}>← 返回主控台</button>
        <div>
          <span className="section-eyebrow">Yachiyo Tasks</span>
          <h1>任务</h1>
          <p>查看 Chat、Bubble 和 Live2D 委派给八千代的 Agent 任务。</p>
        </div>
        <button
          type="button"
          className="hy-btn hy-btn-ghost"
          data-testid="yachiyo-tasks-refresh"
          disabled={loading}
          onClick={() => void refreshTasks()}
        >
          {loading ? '刷新中...' : '刷新'}
        </button>
      </header>

      <div className="yachiyo-tasks-toolbar">
        <button
          type="button"
          className={filter === 'active' ? 'active' : ''}
          data-testid="yachiyo-tasks-filter-active"
          onClick={() => setFilter('active')}
        >
          进行中
          <span>{activeTasks.length}</span>
        </button>
        <button
          type="button"
          className={filter === 'all' ? 'active' : ''}
          data-testid="yachiyo-tasks-filter-all"
          onClick={() => setFilter('all')}
        >
          全部
          <span>{tasks.length}</span>
        </button>
      </div>

      {status ? <div className="notice">{status}</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      <div className="yachiyo-tasks-list" data-testid="yachiyo-tasks-list">
        {visibleTasks.map((task) => (
          <AgentTaskCard
            busy={Boolean(busyActionId)}
            key={task.task_id}
            onApproveApproval={(nextTask, approval) => resolveTaskApproval(nextTask, approval, 'approve')}
            onCancelTask={cancelTask}
            onOpenStudio={openTaskInStudio}
            onRejectApproval={(nextTask, approval) => resolveTaskApproval(nextTask, approval, 'reject')}
            task={task}
          />
        ))}
      </div>

      {!loading && !visibleTasks.length ? (
        <div className="empty-state inline-empty" data-testid="yachiyo-tasks-empty">
          {filter === 'active' ? '暂无进行中的 Agent 任务。' : '暂无 Agent 任务。'}
        </div>
      ) : null}
    </section>
  );
}

function sortTasks(tasks: AgentTaskSnapshot[]): AgentTaskSnapshot[] {
  return [...tasks].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at || left.created_at || '') || 0;
    const rightTime = Date.parse(right.updated_at || right.created_at || '') || 0;
    return rightTime - leftTime;
  });
}

function taskStatusMessage(
  task: AgentTaskSnapshot,
  action: 'approve' | 'reject' | 'cancel',
): string {
  if (action === 'approve' && task.status === 'waiting_approval') return '已批准，任务等待下一次审批。';
  if (action === 'approve') return '已批准，任务状态已更新。';
  if (action === 'reject') return '已拒绝，任务状态已更新。';
  if (task.status === 'cancelled') return '任务已取消。';
  return '已请求取消任务。';
}
