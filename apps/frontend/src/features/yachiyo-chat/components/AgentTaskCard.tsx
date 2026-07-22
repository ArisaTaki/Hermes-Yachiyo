import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { RuntimeDebugSummary } from '../../runtime-shared/components/RuntimeDebugSummary';
import { RuntimeExecutionEnvelopeSummary } from '../../runtime-shared/components/RuntimeExecutionEnvelopeSummary';
import type { RuntimeImageArtifactPointSelection } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import {
  runtimeToolRecoveryActionWithInputPatch,
  runtimeToolRecoveryMissingRequiredFields,
  runtimeToolRecoveryRetryAction,
  type RuntimeToolRecoveryAction,
} from '../../runtime-shared/toolRecoveryActions';
import {
  yachiyoTaskReplanRecoveryActions,
  yachiyoTaskRuntimeExecutionRetryActions,
} from '../taskRecoveryActions';
import {
  consumerTaskFailurePresentation,
  type ConsumerFailureKind,
} from '../consumerFailure';
import { useYachiyoTaskEventReplay } from '../hooks/useYachiyoTaskEventReplay';
import {
  yachiyoTaskApprovalStudioTarget,
  yachiyoTaskRunId,
  yachiyoTaskStudioRunId,
  yachiyoTaskStudioUrl,
} from '../taskSnapshots';
import {
  plannerSummaryChips,
  plannerSummaryDetail,
  plannerSummaryFromTask,
  type TaskPlannerSummarySnapshot,
} from '../taskPlannerSummary';
import {
  taskPermissionRecoveryFromEvents as taskPermissionRecoveryFromEventsImpl,
  taskPermissionRecoveryFromTaskFacts as taskPermissionRecoveryFromTaskFactsImpl,
  type TaskPermissionRecovery,
} from '../taskPermissionRecovery';
import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
} from '../types';
import { ApprovalCard } from './ApprovalCard';
import { ArtifactPreview } from './ArtifactPreview';
import { ToolCallSummary } from './ToolCallSummary';

export function AgentTaskCard({
  busy = false,
  onApproveApproval,
  onCancelTask,
  onOpenStudio,
  onRejectApproval,
  onRunRecoveryAction,
  surface = 'task',
  task,
}: {
  busy?: boolean;
  onApproveApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  onCancelTask?: (task: AgentTaskSnapshot) => void | Promise<void>;
  onOpenStudio?: (runId: string | undefined, studioUrl?: string) => void;
  onRejectApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  onRunRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void | Promise<void>;
  surface?: 'chat' | 'task';
  task: AgentTaskSnapshot;
}) {
  const isChatSurface = surface === 'chat';
  const status = task.status || 'running';
  const runId = yachiyoTaskRunId(task);
  const studioRunId = yachiyoTaskStudioRunId(task);
  const studioUrl = yachiyoTaskStudioUrl(task);
  const [runtimeDetailsOpen, setRuntimeDetailsOpen] = useState(false);
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
    toolCallFacts,
  } = useYachiyoTaskEventReplay(task, { enabled: !isChatSurface && runtimeDetailsOpen });
  const [recoveryCoordinate, setRecoveryCoordinate] = useState<TaskRecoveryCoordinate | null>(null);
  const canCancel = onCancelTask && ['queued', 'running', 'waiting_approval'].includes(status);
  const canOfferRecovery = !['completed', 'success', 'succeeded'].includes(status.toLowerCase());
  const hasHeaderActions = Boolean((!isChatSurface && studioRunId && studioUrl && onOpenStudio) || canCancel);
  const permissionRecovery = taskPermissionRecoveryFromTaskFacts(timelineEvents, toolCallFacts);
  const runtimeExecutionRetryActions = yachiyoTaskRuntimeExecutionRetryActions(task);
  const taskRecoveryCoordinate = recoveryCoordinate?.task_id === task.task_id ? recoveryCoordinate : null;
  const canonicalRecoveryItems = taskCanonicalRecoveryItems(
    task,
    permissionRecovery,
    runtimeExecutionRetryActions,
    taskRecoveryCoordinate,
  );
  const visibleRecoveryItems = isChatSurface
    ? chatTaskRecoveryItems(task, canonicalRecoveryItems)
    : canonicalRecoveryItems;
  const hasRecovery = canOfferRecovery && Boolean(
    visibleRecoveryItems.length
    || permissionRecovery
    || (!isChatSurface && task.replan_recoveries?.length),
  );
  const visibleApprovalFacts = isChatSurface
    ? approvalFacts.filter((approval) => (approval.status || 'pending') === 'pending')
    : approvalFacts;
  const normalizedStatus = status.toLowerCase();
  const showChatFailure = isChatSurface && normalizedStatus === 'failed';
  const showChatCancelled = isChatSurface && ['cancelled', 'canceled'].includes(normalizedStatus);
  const chatFailurePresentation = showChatFailure || showChatCancelled
    ? consumerTaskFailurePresentation(task)
    : null;
  const hasChatContent = Boolean(
    canCancel
    || visibleApprovalFacts.length
    || artifactFacts.length
    || hasRecovery
    || chatFailurePresentation
  );
  const recoveryScreenPointContract = taskRecoveryScreenPointContract(permissionRecovery);
  const plannerSummary = plannerSummaryFromTask(task);

  if (isChatSurface && !hasChatContent) return null;

  return (
    <section
      className={`yachiyo-agent-task-card ${status}${isChatSurface ? ' chat-surface' : ''}`}
      data-event-source={timelineEventSource}
      data-task-id={task.task_id}
      data-task-status={status}
      data-run-id={studioRunId || runId}
      data-testid="yachiyo-agent-task-card"
    >
      <header className="yachiyo-agent-task-card-head">
        <span className="yachiyo-agent-task-status">
          {chatFailurePresentation
            ? chatFailureStatusLabel(chatFailurePresentation.kind)
            : taskStatusLabel(status)}
        </span>
        <div>
          <strong>
            {isChatSurface
              ? chatFailurePresentation?.title || chatTaskStatusTitle(status, artifactFacts.length > 0)
              : task.title || 'Yachiyo task'}
          </strong>
          {!isChatSurface && (task.current_step || task.progress_text) ? (
            <p>{task.current_step || task.progress_text}</p>
          ) : null}
        </div>
        {hasHeaderActions ? (
          <div className="yachiyo-agent-task-card-actions">
            {!isChatSurface && studioRunId && studioUrl && onOpenStudio ? (
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
      {!isChatSurface && task.summary ? (
        <p className="yachiyo-agent-task-summary">{task.summary}</p>
      ) : null}
      {isChatSurface && chatFailurePresentation ? (
        <p className="yachiyo-agent-task-summary" data-testid="yachiyo-agent-task-consumer-failure">
          {chatFailurePresentation.detail}
        </p>
      ) : null}
      {!isChatSurface ? (
        <details
          className="yachiyo-agent-task-runtime-details run-detail-fold"
          data-testid="yachiyo-agent-task-runtime-details"
          onToggle={(event) => setRuntimeDetailsOpen(event.currentTarget.open)}
        >
          <summary className="yachiyo-agent-task-runtime-details-summary">
            <UiIcon name="activity" />
            <span>运行详情</span>
            {replayLoading ? <small>正在加载事件…</small> : null}
          </summary>
          {runtimeDetailsOpen ? (
            <div
              className="yachiyo-agent-task-runtime-details-body run-detail-fold-body"
              data-testid="yachiyo-agent-task-runtime-details-body"
            >
            {plannerSummary ? <TaskPlannerSummary summary={plannerSummary} /> : null}
            {task.runtime_execution_envelope ? (
              <RuntimeExecutionEnvelopeSummary
                envelope={task.runtime_execution_envelope}
                leading={<UiIcon name="activity" title="Runtime Execution" />}
                testId="yachiyo-agent-task-runtime-execution"
                variant="chat"
              />
            ) : null}
            <TaskCoreProgress task={task} />
            <RuntimeDebugSummary
              className="yachiyo-agent-task-runtime-debug"
              compact
              sourceLabel="Task runtime"
              summary={task.runtime_debug}
              testId="yachiyo-agent-task-runtime-debug"
            />
            {timelineEvents.length || toolCallFacts.length ? (
              <ToolCallSummary events={timelineEvents} toolCalls={toolCallFacts} />
            ) : null}
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
            </div>
          ) : null}
        </details>
      ) : null}
      {hasRecovery ? (
        <TaskCanonicalRecoverySummary
          busy={busy}
          items={visibleRecoveryItems}
          onRunRecoveryAction={onRunRecoveryAction}
          permissionRecovery={permissionRecovery}
          recoveries={task.replan_recoveries || []}
          surface={surface}
          task={task}
          taskRecoveryCoordinate={taskRecoveryCoordinate}
        />
      ) : null}
      {visibleApprovalFacts.length ? (
        <div className="yachiyo-agent-task-approvals">
          {visibleApprovalFacts.slice(0, 2).map((approval, approvalIndex) => {
            const pending = (approval.status || 'pending') === 'pending';
            const actionable = pending
              && Boolean(String(approval.approval_id || '').trim())
              && (onApproveApproval || onRejectApproval);
            const {
              runId: approvalStudioRunId,
              studioUrl: approvalStudioUrl,
            } = yachiyoTaskApprovalStudioTarget(task, approval);
            const canOpenApprovalStudio = Boolean(
              !isChatSurface && onOpenStudio && (approvalStudioRunId || approvalStudioUrl),
            );
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
                key={approval.approval_id || `${approval.run_id || runId}:${approval.tool_name}:${approvalIndex}`}
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
          {artifactFacts.slice(0, 3).map((artifact) => {
            const enableImagePointSelection = taskArtifactMatchesRecoveryScreenPoint(
              artifact,
              recoveryScreenPointContract,
            );
            return (
              <ArtifactPreview
                artifact={artifact}
                enableImagePointSelection={enableImagePointSelection}
                key={artifact.artifact_id}
                onSelectImagePoint={(selection) => {
                  setRecoveryCoordinate(taskRecoveryCoordinateFromSelection(task.task_id, selection));
                }}
                presentationMode={isChatSurface ? 'consumer' : 'diagnostic'}
                selectedImagePoint={taskRecoverySelectedPointForArtifact(taskRecoveryCoordinate, artifact)}
                taskId={task.task_id}
              />
            );
          })}
          {isChatSurface && artifactFacts.length > 3
          && onOpenStudio
          && (studioRunId || studioUrl) ? (
            <button
              type="button"
              data-testid="yachiyo-agent-task-open-more-artifacts"
              onClick={() => {
                if (studioUrl) {
                  onOpenStudio(undefined, studioUrl);
                  return;
                }
                onOpenStudio(studioRunId || runId);
              }}
            >
              查看更多结果
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

type TaskCoreTodo = NonNullable<NonNullable<AgentTaskSnapshot['task_core']>['todos']>[number];
type TaskCoreWorkspaceItem = NonNullable<NonNullable<NonNullable<AgentTaskSnapshot['task_core']>['workspace']>['items']>[number];
type TaskCoreCheckpoint = NonNullable<NonNullable<AgentTaskSnapshot['task_core']>['checkpoints']>[number];
type TaskReplanRecoverySnapshot = NonNullable<AgentTaskSnapshot['replan_recoveries']>[number];
type TaskCanonicalRecoverySource = 'permission' | 'replan' | 'runtime';
type TaskCanonicalRecoveryItem = {
  action: TaskPermissionRecoveryAction;
  identity: string;
  sources: TaskCanonicalRecoverySource[];
};

function TaskCoreProgress({ task }: { task: AgentTaskSnapshot }) {
  const progress = task.task_progress;
  const todos = (task.task_core?.todos || [])
    .filter((todo) => todo.todo_id || todo.title);
  const workspaceItems = (task.task_core?.workspace?.items || [])
    .filter((item) => item.item_id || item.title || item.path);
  const checkpoints = (task.task_core?.checkpoints || [])
    .filter((checkpoint) => checkpoint.checkpoint_id || checkpoint.title);
  if (!todos.length && !workspaceItems.length && !checkpoints.length && !progress) return null;

  const visibleTodos = todos.slice(0, 4);
  const visibleWorkspaceItems = workspaceItems.slice(0, 2);
  const visibleCheckpoints = checkpoints.slice(0, 2);
  const totalCount = progress?.total_todos ?? todos.length;
  const completedCount = progress?.completed_todos ?? todos.filter((todo) => todo.status === 'completed').length;
  const blockedCount = progress?.blocked_todos ?? todos.filter((todo) => todo.status === 'blocked').length;
  const activeCount = progress?.active_todos ?? todos.filter((todo) => todo.status === 'in_progress').length;
  const checkpointCount = progress?.total_checkpoints ?? (task.task_core?.checkpoints || []).length;
  const completedCheckpointCount = progress?.completed_checkpoints
    ?? checkpoints.filter((checkpoint) => checkpoint.status === 'completed').length;
  const workspaceItemCount = progress?.total_workspace_items ?? workspaceItems.length;
  const completedWorkspaceItemCount = progress?.completed_workspace_items
    ?? workspaceItems.filter((item) => item.status === 'completed').length;
  const blockedWorkspaceItemCount = progress?.blocked_workspace_items
    ?? workspaceItems.filter((item) => item.status === 'blocked').length;
  const pendingVerificationCount = progress?.pending_verification_count ?? 0;
  const failedVerificationCount = progress?.failed_verification_count ?? 0;
  const progressDetail = progress?.progress_text
    || (totalCount ? `${completedCount}/${totalCount}` : progress?.status || '');
  const activeTodo = todos.find((todo) => todo.status === 'in_progress' || todo.status === 'blocked')
    || todos.find((todo) => todo.status === 'pending')
    || todos[todos.length - 1];

  return (
    <div
      className="yachiyo-agent-task-core"
      data-active-count={activeCount}
      data-blocked-count={blockedCount}
      data-checkpoint-count={checkpointCount}
      data-completed-checkpoint-count={completedCheckpointCount}
      data-completed-count={completedCount}
      data-completed-workspace-count={completedWorkspaceItemCount}
      data-blocked-workspace-count={blockedWorkspaceItemCount}
      data-latest-replan-request-id={progress?.latest_replan_request_id || ''}
      data-latest-verification-status={progress?.latest_verification_status || ''}
      data-needs-replan={String(progress?.needs_replan === true)}
      data-desktop-provider-session-needed={String(progress?.desktop_provider_session_needed === true)}
      data-desktop-provider-session-running={String(progress?.desktop_provider_session_running === true)}
      data-desktop-provider-session-status={progress?.desktop_provider_session_status || ''}
      data-pending-verification-count={pendingVerificationCount}
      data-failed-verification-count={failedVerificationCount}
      data-progress-status={progress?.status || ''}
      data-testid="yachiyo-agent-task-core"
      data-todo-count={totalCount}
      data-workspace-item-count={workspaceItemCount}
    >
      <UiIcon name="activity" title="Task Core" />
      <div className="yachiyo-agent-task-core-body">
        <div className="yachiyo-agent-task-core-head">
          <strong>Task Core</strong>
          <span>
            {progressDetail || `${completedCount}/${totalCount}`}
            {activeTodo ? ` · ${activeTodo.title || activeTodo.step_id || 'ready'}` : ''}
            {progress?.desktop_provider_session_needed
              ? ` · provider ${progress.desktop_provider_session_running ? 'ready' : progress.desktop_provider_session_status || 'waiting'}`
              : ''}
          </span>
        </div>
        {visibleTodos.length ? (
          <div className="yachiyo-agent-task-core-todos">
            {visibleTodos.map((todo) => (
              <span
                className={`yachiyo-agent-task-core-todo ${taskCoreTodoTone(todo.status)}`}
                data-task-todo-id={todo.todo_id}
                data-task-todo-status={todo.status || 'pending'}
                key={todo.todo_id || todo.step_id || todo.title}
                title={taskCoreTodoTitle(todo)}
              >
                <i aria-hidden="true" />
                <span>{todo.title || todo.step_id || todo.tool_name || 'Task step'}</span>
              </span>
            ))}
            {todos.length > visibleTodos.length ? (
              <span className="yachiyo-agent-task-core-more">+{todos.length - visibleTodos.length}</span>
            ) : null}
          </div>
        ) : null}
        {visibleWorkspaceItems.length || visibleCheckpoints.length || workspaceItemCount || checkpointCount ? (
          <div className="yachiyo-agent-task-core-milestones">
            {visibleWorkspaceItems.map((item) => (
              <span
                className={`yachiyo-agent-task-core-chip workspace ${taskCoreMilestoneTone(item.status)}`}
                data-task-workspace-item-id={item.item_id}
                data-task-workspace-item-kind={item.kind || ''}
                data-task-workspace-item-status={item.status || 'pending'}
                key={`workspace:${item.item_id || item.path || item.title}`}
                title={taskCoreWorkspaceItemTitle(item)}
              >
                workspace · {item.title || item.path || item.item_id || 'item'}
              </span>
            ))}
            {workspaceItems.length > visibleWorkspaceItems.length ? (
              <span
                className={`yachiyo-agent-task-core-chip workspace ${blockedWorkspaceItemCount ? 'blocked' : ''}`}
                data-task-workspace-item-more={workspaceItems.length - visibleWorkspaceItems.length}
              >
                workspace · {completedWorkspaceItemCount}/{workspaceItemCount}
              </span>
            ) : null}
            {visibleCheckpoints.map((checkpoint) => (
              <span
                className={`yachiyo-agent-task-core-chip checkpoint ${taskCoreMilestoneTone(checkpoint.status)}`}
                data-task-checkpoint-id={checkpoint.checkpoint_id}
                data-task-checkpoint-status={checkpoint.status || 'planned'}
                key={`checkpoint:${checkpoint.checkpoint_id || checkpoint.after_step_id || checkpoint.title}`}
                title={taskCoreCheckpointTitle(checkpoint)}
              >
                check · {checkpoint.title || checkpoint.checkpoint_id || 'checkpoint'}
              </span>
            ))}
            {checkpoints.length > visibleCheckpoints.length ? (
              <span
                className="yachiyo-agent-task-core-chip checkpoint"
                data-task-checkpoint-more={checkpoints.length - visibleCheckpoints.length}
              >
                check · {completedCheckpointCount}/{checkpointCount}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TaskPlannerSummary({ summary }: { summary: TaskPlannerSummarySnapshot }) {
  const chips = plannerSummaryChips(summary);
  return (
    <div
      className="yachiyo-agent-task-planner"
      data-intent-kind={summary.intentKind}
      data-plan-approvals={summary.approvals.join(',')}
      data-plan-artifacts={summary.artifacts.join(',')}
      data-plan-capabilities={summary.capabilities.join(',')}
      data-plan-followup-targets={summary.followupTargets.join(',')}
      data-plan-missing-capabilities={summary.missingCapabilities.join(',')}
      data-plan-open-questions={summary.openQuestions.join(',')}
      data-plan-tools={summary.tools.join(',')}
      data-route-to-studio={summary.routeToStudio === null ? '' : String(summary.routeToStudio)}
      data-testid="yachiyo-agent-task-planner-summary"
    >
      <UiIcon name="activity" title="Runtime Planner" />
      <div className="yachiyo-agent-task-planner-body">
        <div className="yachiyo-agent-task-planner-head">
          <strong>Planner · {summary.intentKind || 'runtime'}</strong>
          <span>{plannerSummaryDetail(summary)}</span>
        </div>
        {chips.length ? (
          <div className="yachiyo-agent-task-planner-chips">
            {chips.map((chip) => (
              <span
                className={`yachiyo-agent-task-planner-chip ${chip.kind}`}
                data-planner-chip-kind={chip.kind}
                data-planner-chip-value={chip.value}
                key={`${chip.kind}:${chip.value}`}
                title={chip.value}
              >
                {chip.label} · {chip.value}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TaskCanonicalRecoverySummary({
  busy = false,
  items,
  onRunRecoveryAction,
  permissionRecovery,
  recoveries,
  surface,
  task,
  taskRecoveryCoordinate,
}: {
  busy?: boolean;
  items: TaskCanonicalRecoveryItem[];
  onRunRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void | Promise<void>;
  permissionRecovery: TaskPermissionRecovery | null;
  recoveries: TaskReplanRecoverySnapshot[];
  surface: 'chat' | 'task';
  task: AgentTaskSnapshot;
  taskRecoveryCoordinate: TaskRecoveryCoordinate | null;
}) {
  const isChatSurface = surface === 'chat';
  const visibleRecoveries = recoveries.slice(0, 3);
  return (
    <div
      className="yachiyo-agent-task-permission-recovery yachiyo-agent-task-canonical-recovery"
      data-blocking-conditions={permissionRecovery?.blockingConditions.join(',') || ''}
      data-desktop-tools={permissionRecovery?.tools.join(',') || ''}
      data-permission-targets={permissionRecovery?.targets.join(',') || ''}
      data-recovery-action-count={items.length}
      data-recovery-kind={permissionRecovery?.kind || (recoveries.length ? 'replan' : 'runtime')}
      data-testid="yachiyo-agent-task-canonical-recovery"
    >
      <UiIcon name={permissionRecovery ? 'diagnostics' : 'retry'} />
      <div>
        <strong>{isChatSurface ? '需要你的操作' : '恢复操作'}</strong>
        <span>
          {isChatSurface
            ? '完成下面的操作后可以继续'
            : permissionRecovery?.labels.length
            ? `${permissionRecovery.labels.join('、')} 未就绪`
            : `${items.length} 个可执行恢复动作`}
        </span>
        {!isChatSurface ? permissionRecovery?.hints.slice(0, 3).map((hint) => (
          <span className="yachiyo-agent-task-recovery-hint" key={hint}>{hint}</span>
        )) : null}
        {!isChatSurface && visibleRecoveries.length ? (
          <div className="yachiyo-agent-task-planner-chips" data-testid="yachiyo-agent-task-recovery-statuses">
            {visibleRecoveries.map((recovery) => (
              <span
                className={`yachiyo-agent-task-planner-chip ${recovery.status === 'completed' ? '' : 'missing'}`}
                data-replan-recovery-request-id={recovery.request_id}
                data-replan-recovery-status={recovery.status || 'requested'}
                key={`recovery-status:${recovery.request_id}`}
              >
                {taskReplanRecoveryLabel(recovery)} · {recovery.status || 'requested'}
              </span>
            ))}
          </div>
        ) : null}
        {items.length ? (
          <div
            className="yachiyo-agent-task-recovery-actions"
            data-testid="yachiyo-agent-task-recovery-actions"
          >
            {items.slice(0, 8).map((item) => {
              const { action } = item;
              const requiredFields = action.required_retry_fields || [];
              const missingFields = runtimeToolRecoveryMissingRequiredFields(action);
              const selectedRetryPoint = action.retry_input_source === 'screen_capture_artifact'
                ? taskRecoveryCoordinate
                : null;
              const actionLabel = isChatSurface
                ? String(task.status || '').toLowerCase() === 'failed'
                  ? action.action_kind === 'permission_recovery' ? '检查权限' : '重试'
                  : action.label || action.prompt || (action.action_kind === 'permission_recovery' ? '检查权限' : '继续')
                : action.action_kind === 'permission_recovery'
                ? action.label
                : action.label || action.prompt || action.tool;
              return (
                <button
                  type="button"
                  className={requiredFields.length ? 'has-retry-contract' : undefined}
                  data-missing-retry-fields={missingFields.join(',')}
                  data-permission-target={action.permission_target || ''}
                  data-recovery-action-id={action.action_id || ''}
                  data-recovery-action-identity={item.identity}
                  data-recovery-kind={action.action_kind || 'recovery'}
                  data-recovery-request-id={action.replan_request_id || ''}
                  data-recovery-sources={item.sources.join(',')}
                  data-recovery-tool={action.tool}
                  data-required-retry-fields={requiredFields.join(',')}
                  data-retry-input-schema={JSON.stringify(action.retry_input_schema || {})}
                  data-retry-input-source={action.retry_input_source || ''}
                  data-selected-retry-x={selectedRetryPoint?.x ?? ''}
                  data-selected-retry-y={selectedRetryPoint?.y ?? ''}
                  data-testid="yachiyo-agent-task-run-recovery-action"
                  disabled={busy || !onRunRecoveryAction || !action.tool || missingFields.length > 0}
                  key={item.identity}
                  onClick={() => void onRunRecoveryAction?.(task, action)}
                  title={isChatSurface ? actionLabel : action.prompt || actionLabel}
                >
                  <UiIcon name={action.action_kind === 'permission_recovery' ? 'settings' : 'retry'} />
                  <span>{actionLabel}</span>
                  {missingFields.length ? (
                    <small className="yachiyo-agent-task-retry-contract">
                      {isChatSurface ? '需要补充信息后才能重试' : `待补参数：${missingFields.join('、')}`}
                    </small>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
      {isChatSurface && permissionRecovery && !items.length ? (
        <a
          href={permissionRecovery.href}
          data-testid="yachiyo-agent-task-open-recovery-help"
        >
          <UiIcon name="settings" />
          <span>查看解决办法</span>
        </a>
      ) : null}
      {!isChatSurface && permissionRecovery ? (
        <a href={permissionRecovery.href} data-testid="yachiyo-agent-task-open-diagnostics">
          <UiIcon name="diagnostics" />
          <span>打开诊断</span>
        </a>
      ) : null}
    </div>
  );
}

function taskReplanRecoveryActions(recovery: TaskReplanRecoverySnapshot): TaskPermissionRecoveryAction[] {
  return yachiyoTaskReplanRecoveryActions(recovery);
}

function taskCanonicalRecoveryItems(
  task: AgentTaskSnapshot,
  permissionRecovery: TaskPermissionRecovery | null,
  runtimeActions: TaskPermissionRecoveryAction[],
  coordinate: TaskRecoveryCoordinate | null,
): TaskCanonicalRecoveryItem[] {
  const byIdentity = new Map<string, TaskCanonicalRecoveryItem>();
  const add = (
    rawAction: TaskPermissionRecoveryAction | null,
    source: TaskCanonicalRecoverySource,
    requestId = '',
  ) => {
    if (!rawAction?.tool) return;
    const action = requestId && !rawAction.replan_request_id
      ? { ...rawAction, replan_request_id: requestId }
      : rawAction;
    const identity = taskCanonicalRecoveryIdentity(action);
    const existing = byIdentity.get(identity);
    if (existing) {
      if (!existing.sources.includes(source)) existing.sources.push(source);
      return;
    }
    byIdentity.set(identity, { action, identity, sources: [source] });
  };

  (task.replan_recoveries || []).forEach((recovery) => {
    taskReplanRecoveryActions(recovery).forEach((action) => {
      add(action, 'replan', String(recovery.request_id || '').trim());
    });
  });
  (permissionRecovery?.actions || []).forEach((rawAction) => {
    const action = rawAction.action_kind
      ? rawAction
      : { ...rawAction, action_kind: 'permission_recovery' as const };
    add(action, 'permission');
    add(
      taskRecoveryRetryActionWithSelectedCoordinate(
        runtimeToolRecoveryRetryAction(action),
        coordinate,
      ),
      'permission',
    );
  });
  runtimeActions.forEach((action) => add(action, 'runtime'));
  return Array.from(byIdentity.values());
}

function chatTaskRecoveryItems(
  task: AgentTaskSnapshot,
  items: TaskCanonicalRecoveryItem[],
): TaskCanonicalRecoveryItem[] {
  const explicitlyActionable = items.filter(({ action, sources }) => (
    sources.includes('permission')
    || action.action_kind === 'permission_recovery'
    || action.approval_required === true
  ));
  if (String(task.status || '').toLowerCase() !== 'failed') return explicitlyActionable;
  const failedCandidates = explicitlyActionable.length ? explicitlyActionable : items;
  const runnableCandidate = failedCandidates.find(
    ({ action }) => runtimeToolRecoveryMissingRequiredFields(action).length === 0,
  );
  return runnableCandidate ? [runnableCandidate] : failedCandidates.slice(0, 1);
}

export function chatTaskHasRunnableRecoveryAction(task: AgentTaskSnapshot): boolean {
  if (['completed', 'success', 'succeeded'].includes(String(task.status || '').toLowerCase())) {
    return false;
  }
  const permissionRecovery = taskPermissionRecoveryFromTaskFactsImpl(
    task.recent_events || [],
    task.tool_calls || [],
  );
  const items = taskCanonicalRecoveryItems(
    task,
    permissionRecovery,
    yachiyoTaskRuntimeExecutionRetryActions(task),
    null,
  );
  return chatTaskRecoveryItems(task, items).some(({ action }) => (
    Boolean(action.tool)
    && runtimeToolRecoveryMissingRequiredFields(action).length === 0
  ));
}

function taskCanonicalRecoveryIdentity(action: TaskPermissionRecoveryAction): string {
  return [
    String(action.replan_request_id || '').trim(),
    String(action.action_id || '').trim(),
    String(action.tool || '').trim(),
    JSON.stringify(taskCanonicalRecoveryValue(action.input || {})),
  ].join(':');
}

function taskCanonicalRecoveryValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => taskCanonicalRecoveryValue(item));
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, taskCanonicalRecoveryValue(item)]),
  );
}

function taskReplanRecoveryLabel(recovery: TaskReplanRecoverySnapshot): string {
  return String(
    recovery.recovery_action_label
    || recovery.selected_tool_name
    || recovery.target_capability_id
    || recovery.source_tool_name
    || recovery.trigger
    || recovery.request_id
    || 'recovery',
  ).trim();
}

function taskCoreTodoTone(status: unknown): string {
  const value = String(status || 'pending').trim();
  if (value === 'completed' || value === 'blocked' || value === 'skipped' || value === 'in_progress') {
    return value;
  }
  return 'pending';
}

function taskCoreTodoTitle(todo: TaskCoreTodo): string {
  return [
    todo.title,
    todo.tool_name,
    todo.capability_id,
    todo.reason,
  ].filter(Boolean).join(' · ');
}

function taskCoreWorkspaceItemTitle(item: TaskCoreWorkspaceItem): string {
  return [
    item.title,
    item.kind,
    item.path,
    item.description,
    item.source_step_id,
  ].filter(Boolean).join(' · ');
}

function taskCoreCheckpointTitle(checkpoint: TaskCoreCheckpoint): string {
  return [
    checkpoint.title,
    checkpoint.after_step_id,
    ...(checkpoint.verifies || []),
  ].filter(Boolean).join(' · ');
}

function taskCoreMilestoneTone(status: unknown): string {
  const value = String(status || '').trim();
  if (value === 'completed' || value === 'skipped') return value;
  if (value === 'blocked' || value === 'waiting_approval') return 'blocked';
  if (value === 'in_progress' || value === 'ready') return 'in_progress';
  return 'pending';
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

function chatTaskStatusTitle(status: string, hasArtifacts: boolean) {
  if (status === 'queued' || status === 'running') return '正在处理';
  if (status === 'waiting_approval') return '需要你的确认';
  if (status === 'failed') return '没有完成';
  if (status === 'cancelled') return '任务已取消';
  if (hasArtifacts) return '已生成内容';
  return '任务状态';
}

function chatFailureStatusLabel(kind: ConsumerFailureKind) {
  if (kind === 'approval_required') return '待确认';
  if (kind === 'permission_required') return '需授权';
  if (kind === 'cancelled') return '已取消';
  if (kind === 'verification_failed') return '待验证';
  if (kind === 'content_not_found' || kind === 'app_not_found' || kind === 'target_not_found') {
    return '未找到';
  }
  return '未完成';
}

export type TaskPermissionRecoveryAction = RuntimeToolRecoveryAction;

type TaskRecoveryCoordinate = {
  artifact_id: string;
  artifact_path: string;
  kind?: string | null;
  natural_height: number;
  natural_width: number;
  source_tool?: string | null;
  task_id: string;
  x: number;
  y: number;
};

type TaskRecoveryScreenPointContract = {
  artifactKind: string;
  artifactTool: string;
};

function taskRecoveryRetryActionWithSelectedCoordinate(
  action: RuntimeToolRecoveryAction | null,
  coordinate: TaskRecoveryCoordinate | null,
): RuntimeToolRecoveryAction | null {
  if (!action || !coordinate || action.retry_input_source !== 'screen_capture_artifact') return action;
  const inputPatch: Record<string, unknown> = {};
  if (taskRecoveryActionNeedsRetryField(action, 'x')) inputPatch.x = coordinate.x;
  if (taskRecoveryActionNeedsRetryField(action, 'y')) inputPatch.y = coordinate.y;
  return Object.keys(inputPatch).length
    ? runtimeToolRecoveryActionWithInputPatch(action, inputPatch)
    : action;
}

function taskRecoveryActionNeedsRetryField(action: RuntimeToolRecoveryAction, field: string): boolean {
  return (action.required_retry_fields || []).includes(field)
    || runtimeToolRecoveryMissingRequiredFields(action).includes(field);
}

function taskRecoveryScreenPointContract(
  recovery: TaskPermissionRecovery | null,
): TaskRecoveryScreenPointContract | null {
  const action = (recovery?.actions || [])
    .map((candidate) => runtimeToolRecoveryRetryAction(candidate))
    .find((candidate): candidate is RuntimeToolRecoveryAction => {
      if (!candidate || candidate.retry_input_source !== 'screen_capture_artifact') return false;
      return taskRecoveryActionNeedsRetryField(candidate, 'x')
        || taskRecoveryActionNeedsRetryField(candidate, 'y');
    });
  if (!action) return null;
  return {
    artifactKind: action.retry_artifact_kind || 'image',
    artifactTool: action.retry_artifact_tool || 'screen.capture',
  };
}

function taskArtifactMatchesRecoveryScreenPoint(
  artifact: NonNullable<AgentTaskSnapshot['artifacts']>[number],
  contract: TaskRecoveryScreenPointContract | null,
): boolean {
  if (!contract) return false;
  const kind = String(artifact.kind || '').trim();
  const mimeType = String(artifact.mime_type || '').trim();
  const path = String(artifact.path || '').trim();
  const sourceTool = String(artifact.source_tool || '').trim();
  if (sourceTool && contract.artifactTool && sourceTool !== contract.artifactTool) return false;
  if (kind && contract.artifactKind && kind !== contract.artifactKind) return false;
  return kind === 'image'
    || mimeType.startsWith('image/')
    || /\.(?:png|jpe?g|webp|gif)$/i.test(path);
}

function taskRecoveryCoordinateFromSelection(
  taskId: string,
  selection: RuntimeImageArtifactPointSelection,
): TaskRecoveryCoordinate {
  return {
    artifact_id: selection.artifact.artifact_id,
    artifact_path: selection.artifact_path,
    kind: selection.artifact.kind,
    natural_height: selection.natural_height,
    natural_width: selection.natural_width,
    source_tool: selection.artifact.source_tool,
    task_id: taskId,
    x: selection.x,
    y: selection.y,
  };
}

function taskRecoverySelectedPointForArtifact(
  coordinate: TaskRecoveryCoordinate | null,
  artifact: NonNullable<AgentTaskSnapshot['artifacts']>[number],
): TaskRecoveryCoordinate | null {
  if (!coordinate) return null;
  const artifactId = String(artifact.artifact_id || '').trim();
  const artifactPath = String(artifact.path || '').trim();
  if (artifactId && coordinate.artifact_id && artifactId !== coordinate.artifact_id) return null;
  if (artifactPath && coordinate.artifact_path && artifactPath !== coordinate.artifact_path) return null;
  return coordinate;
}

export function taskPermissionRecoveryFromEvents(
  events: AgentTaskSnapshot['recent_events'],
): TaskPermissionRecovery | null {
  return taskPermissionRecoveryFromTaskFacts(events, []);
}

export function taskPermissionRecoveryFromTaskFacts(
  events: AgentTaskSnapshot['recent_events'],
  toolCalls: AgentTaskSnapshot['tool_calls'] = [],
): TaskPermissionRecovery | null {
  return taskPermissionRecoveryFromTaskFactsImpl(events, toolCalls);
}
