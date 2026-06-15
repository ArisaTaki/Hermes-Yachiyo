import { UiIcon } from '../../../components/UiIcon';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import type { AgentTaskSnapshot, ApprovalCardSnapshot } from '../types';
import { ApprovalCard } from './ApprovalCard';
import { ArtifactPreview } from './ArtifactPreview';

export function AgentTaskCard({
  busy = false,
  onApproveApproval,
  onCancelTask,
  onOpenStudio,
  onRejectApproval,
  task,
}: {
  busy?: boolean;
  onApproveApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  onCancelTask?: (task: AgentTaskSnapshot) => void | Promise<void>;
  onOpenStudio?: (runId: string) => void;
  onRejectApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  task: AgentTaskSnapshot;
}) {
  const status = task.status || 'running';
  const runId = taskRunId(task);
  const approvals = task.pending_approvals || [];
  const artifacts = task.artifacts || [];
  const recentEvents = task.recent_events || [];
  const canCancel = onCancelTask && ['queued', 'running', 'waiting_approval'].includes(status);
  const hasHeaderActions = Boolean((runId && onOpenStudio) || canCancel);
  return (
    <section
      className={`yachiyo-agent-task-card ${status}`}
      data-task-id={task.task_id}
      data-task-status={status}
      data-run-id={runId}
      data-testid="yachiyo-agent-task-card"
    >
      <header className="yachiyo-agent-task-card-head">
        <span className="yachiyo-agent-task-status">{taskStatusLabel(status)}</span>
        <div>
          <strong>{task.title || 'Yachiyo task'}</strong>
          {task.current_step || task.progress_text ? (
            <p>{task.current_step || task.progress_text}</p>
          ) : null}
        </div>
        {hasHeaderActions ? (
          <div className="yachiyo-agent-task-card-actions">
            {runId && onOpenStudio ? (
              <button
                type="button"
                data-run-id={runId}
                data-testid="yachiyo-agent-task-open-studio"
                onClick={() => onOpenStudio(runId)}
              >
                <UiIcon name="activity" />
                <span>在 Agent Studio 中查看</span>
              </button>
            ) : null}
            {canCancel ? (
              <button
                type="button"
                data-task-id={task.task_id}
                data-testid="yachiyo-agent-task-cancel"
                disabled={busy}
                onClick={() => void onCancelTask?.(task)}
              >
                <UiIcon name="stop" />
                <span>取消任务</span>
              </button>
            ) : null}
          </div>
        ) : null}
      </header>
      {task.summary ? <p className="yachiyo-agent-task-summary">{task.summary}</p> : null}
      {recentEvents.length ? (
        <RuntimeTimelineSummary
          className="yachiyo-agent-task-timeline"
          events={recentEvents}
          testId="yachiyo-agent-task-timeline"
        />
      ) : null}
      {approvals.length ? (
        <div className="yachiyo-agent-task-approvals">
          {approvals.slice(0, 2).map((approval) => {
            const pending = (approval.status || 'pending') === 'pending';
            const actionable = pending && (onApproveApproval || onRejectApproval);
            const actions = actionable ? (
              <>
                {onApproveApproval ? (
                  <button
                    type="button"
                    data-approval-id={approval.approval_id}
                    data-testid="yachiyo-task-approval-approve"
                    disabled={busy}
                    onClick={() => void onApproveApproval(task, approval)}
                  >
                    <UiIcon name="check" />
                    <span>批准</span>
                  </button>
                ) : null}
                {onRejectApproval ? (
                  <button
                    type="button"
                    data-approval-id={approval.approval_id}
                    data-testid="yachiyo-task-approval-reject"
                    disabled={busy}
                    onClick={() => void onRejectApproval(task, approval)}
                  >
                    <UiIcon name="close" />
                    <span>拒绝</span>
                  </button>
                ) : null}
              </>
            ) : null;
            return (
              <ApprovalCard actions={actions} approval={approval} key={approval.approval_id} />
            );
          })}
        </div>
      ) : null}
      {artifacts.length ? (
        <div className="yachiyo-agent-task-artifacts">
          {artifacts.slice(0, 3).map((artifact) => (
            <ArtifactPreview artifact={artifact} key={artifact.artifact_id} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function taskRunId(task: AgentTaskSnapshot) {
  const artifactRun = task.artifacts?.find((artifact) => artifact.run_id || artifact.source_run_id);
  return (
    task.recent_events?.find((event) => event.run_id)?.run_id
    || task.pending_approvals?.find((approval) => approval.run_id)?.run_id
    || artifactRun?.run_id
    || artifactRun?.source_run_id
    || task.task_id
  );
}

function taskStatusLabel(status: string) {
  if (status === 'queued') return '排队中';
  if (status === 'running') return '执行中';
  if (status === 'waiting_approval') return '待审批';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return status || '任务';
}
