import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { RuntimeDebugSummary } from '../../runtime-shared/components/RuntimeDebugSummary';
import { RuntimeExecutionEnvelopeSummary } from '../../runtime-shared/components/RuntimeExecutionEnvelopeSummary';
import type { RuntimeImageArtifactPointSelection } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { runtimeEventIsDesktopReadinessRecovered } from '../../runtime-shared/desktopEvents';
import {
  runtimeToolRecoveryActionWithInputPatch,
  runtimeToolRecoveryActionsFromRecords,
  runtimeToolRecoveryMissingRequiredFields,
  runtimeToolRecoveryRetryAction,
  type RuntimeToolRecoveryAction,
} from '../../runtime-shared/toolRecoveryActions';
import { runtimeToolRecoveryHintsFromRecords } from '../../runtime-shared/toolRecoveryHints';
import {
  yachiyoTaskReplanRecoveryActions,
  yachiyoTaskRuntimeExecutionRetryActions,
} from '../taskRecoveryActions';
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
  task,
}: {
  busy?: boolean;
  onApproveApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  onCancelTask?: (task: AgentTaskSnapshot) => void | Promise<void>;
  onOpenStudio?: (runId: string | undefined, studioUrl?: string) => void;
  onRejectApproval?: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void | Promise<void>;
  onRunRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void | Promise<void>;
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
    toolCallFacts,
  } = useYachiyoTaskEventReplay(task);
  const [recoveryCoordinate, setRecoveryCoordinate] = useState<TaskRecoveryCoordinate | null>(null);
  const canCancel = onCancelTask && ['queued', 'running', 'waiting_approval'].includes(status);
  const hasHeaderActions = Boolean((studioRunId && studioUrl && onOpenStudio) || canCancel);
  const permissionRecovery = taskPermissionRecoveryFromTaskFacts(timelineEvents, toolCallFacts);
  const runtimeExecutionRetryActions = yachiyoTaskRuntimeExecutionRetryActions(task);
  const taskRecoveryCoordinate = recoveryCoordinate?.task_id === task.task_id ? recoveryCoordinate : null;
  const recoveryScreenPointContract = taskRecoveryScreenPointContract(permissionRecovery);
  const plannerSummary = plannerSummaryFromTask(task);

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
      {plannerSummary ? <TaskPlannerSummary summary={plannerSummary} /> : null}
      {task.runtime_execution_envelope ? (
        <RuntimeExecutionEnvelopeSummary
          envelope={task.runtime_execution_envelope}
          leading={<UiIcon name="activity" title="Runtime Execution" />}
          testId="yachiyo-agent-task-runtime-execution"
          variant="chat"
        />
      ) : null}
      {runtimeExecutionRetryActions.length ? (
        <TaskRuntimeExecutionRetryActions
          actions={runtimeExecutionRetryActions}
          busy={busy}
          onRunRecoveryAction={onRunRecoveryAction}
          task={task}
        />
      ) : null}
      {task.replan_recoveries?.length ? (
        <TaskReplanRecoverySummary
          busy={busy}
          onRunRecoveryAction={onRunRecoveryAction}
          recoveries={task.replan_recoveries}
          task={task}
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
      {permissionRecovery ? (
        <div
          className="yachiyo-agent-task-permission-recovery"
          data-blocking-conditions={permissionRecovery.blockingConditions.join(',')}
          data-desktop-tools={permissionRecovery.tools.join(',')}
          data-permission-targets={permissionRecovery.targets.join(',')}
          data-recovery-kind={permissionRecovery.kind}
          data-testid="yachiyo-agent-task-permission-recovery"
        >
          <UiIcon name="diagnostics" />
          <div>
            <strong>
              {permissionRecovery.kind === 'permission'
                ? '需要恢复桌面权限'
                : permissionRecovery.kind === 'blocking_condition'
                  ? '运行条件阻塞'
                  : '需要处理运行环境'}
            </strong>
            <span>{permissionRecovery.labels.join('、')} 未就绪</span>
            {permissionRecovery.hints.map((hint) => (
              <span className="yachiyo-agent-task-recovery-hint" key={hint}>{hint}</span>
            ))}
            {permissionRecovery.actions.length ? (
              <div
                className="yachiyo-agent-task-recovery-actions"
                data-testid="yachiyo-agent-task-recovery-actions"
              >
                {permissionRecovery.actions.slice(0, 3).flatMap((action) => {
                  const retryAction = taskRecoveryRetryActionWithSelectedCoordinate(
                    runtimeToolRecoveryRetryAction(action),
                    taskRecoveryCoordinate,
                  );
                  const retryFields = retryAction?.required_retry_fields || [];
                  const missingRetryFields = retryAction ? runtimeToolRecoveryMissingRequiredFields(retryAction) : [];
                  const retryInputSource = retryAction?.retry_input_source === 'screen_capture_artifact'
                    ? '截图定位'
                    : '';
                  const selectedRetryPoint = retryInputSource && taskRecoveryCoordinate
                    ? taskRecoveryCoordinate
                    : null;
                  return [
                    <button
                      type="button"
                      data-permission-target={action.permission_target}
                      data-recovery-kind="permission_recovery"
                      data-recovery-tool={action.tool}
                      data-testid="yachiyo-agent-task-run-recovery-action"
                      disabled={busy || !onRunRecoveryAction}
                      key={`${action.tool}:${action.prompt}:${action.permission_target}:recovery`}
                      onClick={() => void onRunRecoveryAction?.(task, action)}
                      title={action.prompt}
                    >
                      <UiIcon name="settings" />
                      <span>{action.label}</span>
                    </button>,
                    retryAction ? (
                      <button
                        type="button"
                        className={retryFields.length ? 'has-retry-contract' : undefined}
                        data-required-retry-fields={retryFields.join(',')}
                        data-missing-retry-fields={missingRetryFields.join(',')}
                        data-permission-target={retryAction.permission_target}
                        data-retry-input-source={retryAction.retry_input_source || ''}
                        data-selected-retry-x={selectedRetryPoint?.x ?? ''}
                        data-selected-retry-y={selectedRetryPoint?.y ?? ''}
                        data-recovery-kind="retry_original"
                        data-recovery-tool={retryAction.tool}
                        data-retry-input-schema={JSON.stringify(retryAction.retry_input_schema || {})}
                        data-testid="yachiyo-agent-task-run-retry-action"
                        disabled={busy || !onRunRecoveryAction || missingRetryFields.length > 0}
                        key={`${retryAction.tool}:${retryAction.prompt}:${retryAction.permission_target}:retry`}
                        onClick={() => void onRunRecoveryAction?.(task, retryAction)}
                        title={retryAction.prompt}
                      >
                        <UiIcon name="retry" />
                        <span>{retryAction.label}</span>
                        {missingRetryFields.length ? (
                          <small className="yachiyo-agent-task-retry-contract">
                            待补参数：{missingRetryFields.join('、')}
                            {retryInputSource ? ` · ${retryInputSource}` : ''}
                          </small>
                        ) : null}
                      </button>
                    ) : null,
                  ];
                })}
              </div>
            ) : null}
          </div>
          <a
            href={permissionRecovery.href}
            data-testid="yachiyo-agent-task-open-diagnostics"
          >
            <UiIcon name="diagnostics" />
            <span>打开诊断</span>
          </a>
        </div>
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
                selectedImagePoint={taskRecoverySelectedPointForArtifact(taskRecoveryCoordinate, artifact)}
                taskId={task.task_id}
              />
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

type TaskCoreTodo = NonNullable<NonNullable<AgentTaskSnapshot['task_core']>['todos']>[number];
type TaskCoreWorkspaceItem = NonNullable<NonNullable<NonNullable<AgentTaskSnapshot['task_core']>['workspace']>['items']>[number];
type TaskCoreCheckpoint = NonNullable<NonNullable<AgentTaskSnapshot['task_core']>['checkpoints']>[number];
type TaskReplanRecoverySnapshot = NonNullable<AgentTaskSnapshot['replan_recoveries']>[number];
type TaskReplanRecoveryRow = {
  actions: TaskPermissionRecoveryAction[];
  recovery: TaskReplanRecoverySnapshot;
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

function TaskReplanRecoverySummary({
  busy = false,
  onRunRecoveryAction,
  recoveries,
  task,
}: {
  busy?: boolean;
  onRunRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void | Promise<void>;
  recoveries: TaskReplanRecoverySnapshot[];
  task: AgentTaskSnapshot;
}) {
  const rows = recoveries.map((recovery) => ({
    actions: taskReplanRecoveryActions(recovery),
    recovery,
  }));
  const visibleRows = rows.slice(0, 4);
  const actionItems = rows
    .flatMap((row) => row.actions.map((action, index) => ({ action, index, recovery: row.recovery })))
    .slice(0, 5);
  const actionCount = rows.reduce((count, row) => count + row.actions.length, 0);
  const latest = rows[0]?.recovery || null;
  return (
    <div
      className="yachiyo-agent-task-planner yachiyo-agent-task-replan-recovery"
      data-latest-replan-request-id={latest?.request_id || ''}
      data-latest-replan-status={latest?.status || ''}
      data-replan-recovery-action-count={actionCount}
      data-replan-recovery-count={rows.length}
      data-testid="yachiyo-agent-task-replan-recovery"
    >
      <UiIcon name="retry" title="Replan recovery" />
      <div className="yachiyo-agent-task-planner-body">
        <div className="yachiyo-agent-task-planner-head">
          <strong>Recovery plan</strong>
          <span>{taskReplanRecoveryDetail(rows)}</span>
        </div>
        <div className="yachiyo-agent-task-planner-chips">
          {visibleRows.map((row) => (
            <span
              className={`yachiyo-agent-task-planner-chip ${row.recovery.status === 'completed' ? '' : 'missing'}`}
              data-replan-recovery-action-count={row.actions.length}
              data-replan-recovery-id={row.recovery.request_id}
              data-replan-recovery-planning-reason={row.recovery.planning_reason || ''}
              data-replan-recovery-request-id={row.recovery.request_id}
              data-replan-recovery-status={row.recovery.status || 'requested'}
              data-replan-recovery-tool={row.recovery.selected_tool_name || row.recovery.source_tool_name || ''}
              key={`replan:${row.recovery.request_id}`}
              title={taskReplanRecoveryTitle(row)}
            >
              replan · {taskReplanRecoveryLabel(row.recovery)} · {row.recovery.status || 'requested'}
            </span>
          ))}
          {recoveries.length > visibleRows.length ? (
            <span className="yachiyo-agent-task-planner-chip more">
              更多 · {recoveries.length - visibleRows.length}
            </span>
          ) : null}
          {actionItems.map(({ action, index, recovery }) => {
            const inputPreview = taskRecoveryValuePreview(action.input);
            const verificationTargetsPreview = taskRecoveryValuePreview(action.verification_targets || []);
            return (
              <button
                type="button"
                className={`yachiyo-agent-task-planner-chip yachiyo-agent-task-replan-action ${action.approval_required ? 'approval' : ''}`}
                data-replan-recovery-action-approval-required={String(action.approval_required === true)}
                data-replan-recovery-action-id={action.action_id || ''}
                data-replan-recovery-input={inputPreview}
                data-replan-recovery-label={action.label || action.prompt || action.tool}
                data-replan-recovery-permission-target={action.permission_target || ''}
                data-replan-recovery-request-id={recovery.request_id}
                data-replan-recovery-risk={action.risk_level || ''}
                data-replan-recovery-selected={String(action.selected === true)}
                data-replan-recovery-tool={action.tool}
                data-replan-recovery-tool-index={index}
                data-replan-recovery-verification-targets={verificationTargetsPreview}
                data-testid="yachiyo-agent-task-run-replan-recovery-action"
                disabled={busy || !onRunRecoveryAction || !action.tool}
                key={`${recovery.request_id}:action:${action.action_id || action.tool}:${index}`}
                onClick={() => void onRunRecoveryAction?.(task, action)}
                title={[
                  action.prompt,
                  inputPreview ? `input: ${inputPreview}` : '',
                  verificationTargetsPreview ? `verification: ${verificationTargetsPreview}` : '',
                ].filter(Boolean).join(' · ')}
              >
                <UiIcon name="retry" />
                <span>执行 · {action.label || action.tool}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function TaskRuntimeExecutionRetryActions({
  actions,
  busy = false,
  onRunRecoveryAction,
  task,
}: {
  actions: TaskPermissionRecoveryAction[];
  busy?: boolean;
  onRunRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void | Promise<void>;
  task: AgentTaskSnapshot;
}) {
  return (
    <div
      className="yachiyo-agent-task-planner yachiyo-agent-task-runtime-retry"
      data-runtime-retry-action-count={actions.length}
      data-testid="yachiyo-agent-task-runtime-retry-actions"
    >
      <UiIcon name="retry" title="Runtime retry" />
      <div className="yachiyo-agent-task-planner-body">
        <div className="yachiyo-agent-task-planner-head">
          <strong>Runtime retry</strong>
          <span>{actions.length} 个可重试观察/验证动作</span>
        </div>
        <div className="yachiyo-agent-task-planner-chips">
          {actions.map((action, index) => {
            const inputPreview = taskRecoveryValuePreview(action.input);
            return (
              <button
                type="button"
                className="yachiyo-agent-task-planner-chip yachiyo-agent-task-runtime-retry-action"
                data-runtime-retry-action-id={action.action_id || ''}
                data-runtime-retry-input={inputPreview}
                data-runtime-retry-input-source={action.retry_input_source || ''}
                data-runtime-retry-label={action.label || action.prompt || action.tool}
                data-runtime-retry-permission-target={action.permission_target || ''}
                data-runtime-retry-risk={action.risk_level || ''}
                data-runtime-retry-tool={action.tool}
                data-runtime-retry-tool-index={index}
                data-testid="yachiyo-agent-task-run-runtime-retry-action"
                disabled={busy || !onRunRecoveryAction || !action.tool}
                key={`${action.action_id || action.tool}:${index}`}
                onClick={() => void onRunRecoveryAction?.(task, action)}
                title={[
                  action.prompt,
                  inputPreview ? `input: ${inputPreview}` : '',
                ].filter(Boolean).join(' · ')}
              >
                <UiIcon name="retry" />
                <span>重试 · {action.tool}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function taskReplanRecoveryActions(recovery: TaskReplanRecoverySnapshot): TaskPermissionRecoveryAction[] {
  return yachiyoTaskReplanRecoveryActions(recovery);
}

function taskReplanRecoveryDetail(rows: TaskReplanRecoveryRow[]): string {
  const actionCount = rows.reduce((count, row) => count + row.actions.length, 0);
  const pendingCount = rows.filter((row) => (row.recovery.status || 'requested') !== 'completed').length;
  return [
    `${rows.length} 个恢复请求`,
    actionCount ? `${actionCount} 个可执行动作` : '',
    pendingCount ? `${pendingCount} 个待处理` : '',
  ].filter(Boolean).join(' · ');
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

function taskReplanRecoveryTitle(row: TaskReplanRecoveryRow): string {
  return [
    row.recovery.failure_detail,
    row.recovery.planning_reason ? `reason: ${row.recovery.planning_reason}` : '',
    row.recovery.permission_target ? `permission: ${row.recovery.permission_target}` : '',
    row.recovery.risk_level ? `risk: ${row.recovery.risk_level}` : '',
    row.actions.length ? `actions: ${row.actions.map((action) => action.tool).join(', ')}` : '',
  ].filter(Boolean).join(' · ');
}

function taskRecoveryValuePreview(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return truncateTaskRecoveryPreview(value);
  try {
    return truncateTaskRecoveryPreview(JSON.stringify(value));
  } catch {
    return truncateTaskRecoveryPreview(String(value));
  }
}

function truncateTaskRecoveryPreview(value: string): string {
  const text = value.trim();
  return text.length > 140 ? `${text.slice(0, 137)}...` : text;
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

type TaskPermissionRecovery = {
  actions: TaskPermissionRecoveryAction[];
  blockingConditions: string[];
  href: string;
  hints: string[];
  kind: 'permission' | 'blocking_condition' | 'mixed';
  labels: string[];
  targets: string[];
  tools: string[];
};

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

const permissionTargetLabels: Record<string, string> = {
  accessibility: '辅助功能权限',
  automation: '自动化权限',
  automation_or_accessibility: '自动化或辅助功能权限',
  chrome_cdp: 'Chrome CDP',
  music_app: 'Music.app',
  open_command: 'macOS open 命令',
  screen_capture_probe_failed: '屏幕录制探测',
  screen_recording: '屏幕录制权限',
  unsupported_platform: '当前平台',
};

const blockingConditionLabels: Record<string, string> = {
  desktop_session_locked: '桌面会话已锁定',
  foreground_focus_unavailable: '前台激活暂不可用',
  screen_capture_blank: '屏幕画面为空黑',
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

export function taskPermissionRecoveryFromEvents(events: AgentTaskSnapshot['recent_events']): TaskPermissionRecovery | null {
  return taskPermissionRecoveryFromTaskFacts(events, []);
}

export function taskPermissionRecoveryFromTaskFacts(
  events: AgentTaskSnapshot['recent_events'],
  toolCalls: AgentTaskSnapshot['tool_calls'] = [],
): TaskPermissionRecovery | null {
  const safeEvents = events || [];
  const safeToolCalls = toolCalls || [];
  const recoveryBoundary = latestReadinessRecoverySequence(safeEvents);
  const recoveryEvents = safeEvents.filter((event) => recoveryEventSurvivesReadinessRecovery(event, recoveryBoundary));
  const recoveryToolCalls = safeToolCalls.filter((toolCall) => recoveryToolCallSurvivesReadinessRecovery(toolCall, recoveryBoundary));
  const targets = uniqueStrings([
    ...recoveryEvents.flatMap((event) => permissionTargetsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => permissionTargetsFromToolCall(toolCall)),
  ]);
  const blockingConditions = uniqueStrings([
    ...recoveryEvents.flatMap((event) => blockingConditionsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => blockingConditionsFromToolCall(toolCall)),
  ]);
  if (!targets.length && !blockingConditions.length) return null;
  const hints = uniqueStrings([
    ...recoveryEvents.flatMap((event) => recoveryHintsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => recoveryHintsFromToolCall(toolCall)),
  ]);
  const tools = uniqueStrings([
    ...recoveryEvents.flatMap((event) => desktopToolsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => desktopToolsFromToolCall(toolCall)),
  ]);
  const actions = dedupeRecoveryActions([
    ...executableRecoveryActionsFromEvents(recoveryEvents),
    ...executableRecoveryActionsFromToolCalls(recoveryToolCalls),
  ]);
  const params = new URLSearchParams({ command: 'native doctor', return_to: 'chat' });
  if (targets.length) params.set('permission_targets', targets.join(','));
  if (blockingConditions.length) params.set('blocking_conditions', blockingConditions.join(','));
  if (tools.length) params.set('desktop_tools', tools.join(','));
  const kind = targets.length && blockingConditions.length
    ? 'mixed'
    : blockingConditions.length ? 'blocking_condition' : 'permission';
  return {
    actions,
    blockingConditions,
    href: `#/diagnostics?${params.toString()}`,
    hints,
    kind,
    labels: [
      ...targets.map((target) => permissionTargetLabels[target] || target),
      ...blockingConditions.map((condition) => blockingConditionLabels[condition] || condition),
    ],
    targets,
    tools,
  };
}

function latestReadinessRecoverySequence(events: AgentTaskSnapshot['recent_events']): number {
  return Math.max(
    0,
    ...(events || [])
      .filter((event) => runtimeEventIsDesktopReadinessRecovered(String(event.event_type || '').trim()))
      .map((event) => Number(event.sequence) || 0),
  );
}

function recoveryEventSurvivesReadinessRecovery(
  event: NonNullable<AgentTaskSnapshot['recent_events']>[number],
  recoveryBoundary: number,
): boolean {
  const eventType = String(event.event_type || '').trim();
  if (runtimeEventIsDesktopReadinessRecovered(eventType)) return false;
  if (!recoveryBoundary) return true;
  if ((Number(event.sequence) || 0) > recoveryBoundary) return true;
  if (permissionTargetsFromEvent(event).length) return true;
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  return !foregroundReadinessRecordWasRecovered(result) && !foregroundReadinessRecordWasRecovered(payload);
}

function recoveryToolCallSurvivesReadinessRecovery(
  toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number],
  recoveryBoundary: number,
): boolean {
  if (!recoveryBoundary) return true;
  if (permissionTargetsFromToolCall(toolCall).length) return true;
  return !foregroundReadinessRecordWasRecovered(objectValue(toolCall.output_preview));
}

function executableRecoveryActionsFromEvents(events: AgentTaskSnapshot['recent_events']): TaskPermissionRecoveryAction[] {
  return dedupeRecoveryActions((events || []).flatMap((event) => recoveryActionsFromEvent(event)));
}

function executableRecoveryActionsFromToolCalls(toolCalls: AgentTaskSnapshot['tool_calls']): TaskPermissionRecoveryAction[] {
  return dedupeRecoveryActions((toolCalls || []).flatMap((toolCall) => recoveryActionsFromToolCall(toolCall)));
}

function recoveryActionsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): TaskPermissionRecoveryAction[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const retryTool = String(payload.tool || result.tool || result.tool_name || event.detail || '').trim();
  return runtimeToolRecoveryActionsFromRecords(
    [result, payload].filter(Boolean),
    {
      retry_input: objectValue(payload.input_preview || result.input_preview),
      retry_source_event_type: String(event.event_type || '').trim(),
      retry_tool: retryTool,
    },
  );
}

function recoveryActionsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): TaskPermissionRecoveryAction[] {
  const outputPreview = objectValue(toolCall.output_preview);
  return runtimeToolRecoveryActionsFromRecords(
    [outputPreview],
    {
      retry_input: objectValue(toolCall.input_preview),
      retry_source_tool_call_id: String(toolCall.tool_call_id || '').trim(),
      retry_tool: String(toolCall.tool_name || '').trim(),
    },
  );
}

function permissionTargetsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const sources = [result, payload].filter(Boolean);
  const targets = sources.flatMap((source) => [
    ...stringList(source.permission_targets),
    ...stringList(source.missing_permissions),
  ]);
  const permissionError = sources.some((source) => source.permission_error === true);
  return permissionError || targets.length ? targets : [];
}

function permissionTargetsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  const outputPreview = objectValue(toolCall.output_preview);
  const targets = [
    ...stringList(outputPreview.permission_targets),
    ...stringList(outputPreview.missing_permissions),
  ];
  return outputPreview.permission_error === true || targets.length ? targets : [];
}

function blockingConditionsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  return uniqueStrings([
    ...blockingConditionsFromRecord(result),
    ...blockingConditionsFromRecord(payload),
  ]);
}

function blockingConditionsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  return blockingConditionsFromRecord(objectValue(toolCall.output_preview));
}

function blockingConditionsFromRecord(source: Record<string, unknown>): string[] {
  const data = objectValue(source.data);
  return uniqueStrings([
    ...stringList(source.blocking_condition),
    ...stringList(source.blocking_conditions),
    ...stringList(data.blocking_condition),
    ...stringList(data.blocking_conditions),
  ]);
}

function foregroundReadinessRecordWasRecovered(source: Record<string, unknown>): boolean {
  const data = objectValue(source.data);
  const error = String(source.error_code || source.error || data.error_code || data.error || '').trim();
  const conditions = uniqueStrings([
    ...blockingConditionsFromRecord(source),
    error,
  ]);
  if (source.blocked_by_runtime_readiness === true || data.blocked_by_runtime_readiness === true) return true;
  if (data.ready_for_foreground_action === false) return true;
  return conditions.some((condition) => recoverableForegroundReadinessConditions.has(condition));
}

const recoverableForegroundReadinessConditions = new Set([
  'app_not_found',
  'app_not_running',
  'foreground_focus_unverified',
  'foreground_not_ready',
  'no_actionable_controls',
  'ui_elements_empty',
]);

function recoveryHintsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const sources = [result, payload].filter(Boolean);
  return runtimeToolRecoveryHintsFromRecords(sources);
}

function recoveryHintsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  return runtimeToolRecoveryHintsFromRecords([objectValue(toolCall.output_preview)]);
}

function desktopToolsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const detailTool = String(event.event_type || '').includes('tool') ? event.detail : '';
  return [
    result.action,
    result.tool,
    result.tool_name,
    payload.tool,
    payload.tool_name,
    detailTool,
  ].flatMap((value) => stringList(value));
}

function desktopToolsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  const outputPreview = objectValue(toolCall.output_preview);
  return [
    toolCall.tool_name,
    outputPreview.action,
    outputPreview.tool,
    outputPreview.tool_name,
  ].flatMap((value) => stringList(value));
}

function dedupeRecoveryActions(actions: TaskPermissionRecoveryAction[]): TaskPermissionRecoveryAction[] {
  const byKey = new Map<string, TaskPermissionRecoveryAction>();
  actions.forEach((action) => {
    const key = `${action.tool}:${JSON.stringify(action.input)}:${action.permission_target}`;
    if (!byKey.has(key)) byKey.set(key, action);
  });
  return Array.from(byKey.values());
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap((item) => stringList(item));
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)));
}
