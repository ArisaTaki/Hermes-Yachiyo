import { useEffect, useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { listYachiyoTaskEvents } from '../api';
import { yachiyoTaskRunId, yachiyoTaskStudioRunId, yachiyoTaskStudioUrl } from '../taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot, PublicRunEvent } from '../types';
import { ApprovalCard } from './ApprovalCard';
import { ArtifactPreview } from './ArtifactPreview';
import { ToolCallSummary } from './ToolCallSummary';

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
  onOpenStudio?: (runId: string, studioUrl?: string) => void;
  onRejectApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  task: AgentTaskSnapshot;
}) {
  const [replayEvents, setReplayEvents] = useState<PublicRunEvent[]>([]);
  const status = task.status || 'running';
  const runId = yachiyoTaskRunId(task);
  const studioRunId = yachiyoTaskStudioRunId(task);
  const studioUrl = yachiyoTaskStudioUrl(task);
  const approvals = task.pending_approvals || [];
  const artifacts = task.artifacts || [];
  const recentEvents = task.recent_events || [];
  const timelineEvents = replayEvents.length ? replayEvents : recentEvents;
  const timelineEventSource = replayEvents.length ? 'run_event_page' : 'task_snapshot';
  const canCancel = onCancelTask && ['queued', 'running', 'waiting_approval'].includes(status);
  const hasHeaderActions = Boolean((studioRunId && studioUrl && onOpenStudio) || canCancel);

  useEffect(() => {
    const taskId = String(task.task_id || '').trim();
    setReplayEvents([]);
    if (!taskId) return undefined;
    let disposed = false;
    void listYachiyoTaskEvents(taskId, 0, 200)
      .then((page) => {
        if (!disposed) setReplayEvents(page.events || []);
      })
      .catch(() => {
        if (!disposed) setReplayEvents([]);
      });
    return () => {
      disposed = true;
    };
  }, [task.task_id, task.updated_at]);

  return (
    <section
      className={`yachiyo-agent-task-card ${status}`}
      data-event-source={timelineEventSource}
      data-task-id={task.task_id}
      data-task-status={status}
      data-run-id={studioRunId || runId}
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
            {studioRunId && studioUrl && onOpenStudio ? (
              <a
                href={studioUrl}
                data-run-id={studioRunId}
                data-studio-url={studioUrl}
                data-testid="yachiyo-agent-task-open-studio"
                onClick={(event) => {
                  event.preventDefault();
                  onOpenStudio(studioRunId, studioUrl);
                }}
              >
                <UiIcon name="activity" />
                <span>在 Agent Studio 中查看</span>
              </a>
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
      {timelineEvents.length ? <ToolCallSummary events={timelineEvents} /> : null}
      {timelineEvents.length ? (
        <RuntimeTimelineSummary
          className="yachiyo-agent-task-timeline"
          events={timelineEvents}
          testId="yachiyo-agent-task-timeline"
        />
      ) : null}
      {approvals.length ? (
        <div className="yachiyo-agent-task-approvals">
          {approvals.slice(0, 2).map((approval) => {
            const pending = (approval.status || 'pending') === 'pending';
            const actionable = pending && (onApproveApproval || onRejectApproval);
            return (
              <ApprovalCard
                approval={approval}
                busy={busy}
                key={approval.approval_id}
                onApprove={
                  actionable && onApproveApproval
                    ? () => void onApproveApproval(task, approval)
                    : undefined
                }
                onReject={
                  actionable && onRejectApproval
                    ? () => void onRejectApproval(task, approval)
                    : undefined
                }
              />
            );
          })}
        </div>
      ) : null}
      {artifacts.length ? (
        <div className="yachiyo-agent-task-artifacts">
          {artifacts.slice(0, 3).map((artifact) => (
            <ArtifactPreview artifact={artifact} key={artifact.artifact_id} taskId={task.task_id} />
          ))}
        </div>
      ) : null}
    </section>
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
