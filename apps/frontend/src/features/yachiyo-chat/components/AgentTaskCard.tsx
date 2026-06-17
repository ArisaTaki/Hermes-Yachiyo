import { UiIcon } from '../../../components/UiIcon';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { useYachiyoTaskEventReplay } from '../hooks/useYachiyoTaskEventReplay';
import {
  yachiyoTaskApprovalStudioTarget,
  yachiyoTaskRunId,
  yachiyoTaskStudioRunId,
  yachiyoTaskStudioUrl,
} from '../taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot } from '../types';
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
  onOpenStudio?: (runId: string | undefined, studioUrl?: string) => void;
  onRejectApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  task: AgentTaskSnapshot;
}) {
  const status = task.status || 'running';
  const runId = yachiyoTaskRunId(task);
  const studioRunId = yachiyoTaskStudioRunId(task);
  const studioUrl = yachiyoTaskStudioUrl(task);
  const {
    approvalFacts,
    artifactFacts,
    loadMoreTaskEvents,
    replayError,
    replayHasMore,
    replayLoading,
    replayNextAfterSequence,
    timelineEvents,
    timelineEventSource,
    timelineSummaryEvents,
  } = useYachiyoTaskEventReplay(task);
  const canCancel = onCancelTask && ['queued', 'running', 'waiting_approval'].includes(status);
  const hasHeaderActions = Boolean((studioRunId && studioUrl && onOpenStudio) || canCancel);

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
                  onOpenStudio(undefined, studioUrl);
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
          eventTestId="yachiyo-agent-task-timeline-event"
          events={timelineSummaryEvents}
          testId="yachiyo-agent-task-timeline"
        />
      ) : null}
      {replayError ? (
        <p className="yachiyo-agent-task-timeline-status error" data-testid="yachiyo-agent-task-event-error">
          {replayError}
        </p>
      ) : null}
      {replayHasMore ? (
        <button
          type="button"
          className="yachiyo-agent-task-load-events"
          data-next-after-sequence={replayNextAfterSequence}
          data-testid="yachiyo-agent-task-load-more-events"
          disabled={replayLoading}
          onClick={() => void loadMoreTaskEvents()}
        >
          {replayLoading ? '加载任务事件中...' : '加载更多任务事件'}
        </button>
      ) : null}
      {approvalFacts.length ? (
        <div className="yachiyo-agent-task-approvals">
          {approvalFacts.slice(0, 2).map((approval) => {
            const pending = (approval.status || 'pending') === 'pending';
            const actionable = pending && (onApproveApproval || onRejectApproval);
            const {
              runId: approvalStudioRunId,
              studioUrl: approvalStudioUrl,
            } = yachiyoTaskApprovalStudioTarget(task, approval);
            const canOpenApprovalStudio = Boolean(onOpenStudio && (approvalStudioRunId || approvalStudioUrl));
            return (
              <ApprovalCard
                actions={
                  canOpenApprovalStudio ? (
                    <div
                      className="yachiyo-agent-task-approval-actions yachiyo-agent-task-approval-secondary-actions"
                      data-testid="yachiyo-task-approval-secondary-actions"
                    >
                      <a
                        href={approvalStudioUrl || '#'}
                        data-approval-id={approval.approval_id}
                        data-run-id={approvalStudioRunId}
                        data-studio-url={approvalStudioUrl}
                        data-testid="yachiyo-task-approval-open-studio"
                        onClick={(event) => {
                          event.preventDefault();
                          if (approvalStudioUrl) {
                            onOpenStudio?.(undefined, approvalStudioUrl);
                            return;
                          }
                          onOpenStudio?.(approvalStudioRunId);
                        }}
                      >
                        <UiIcon name="activity" />
                        <span>在 Studio 中查看</span>
                      </a>
                    </div>
                  ) : undefined
                }
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
      {artifactFacts.length ? (
        <div className="yachiyo-agent-task-artifacts">
          {artifactFacts.slice(0, 3).map((artifact) => (
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
