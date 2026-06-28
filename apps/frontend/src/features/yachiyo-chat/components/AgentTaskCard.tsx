import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import type { RuntimeImageArtifactPointSelection } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import {
  runtimeToolRecoveryActionWithInputPatch,
  runtimeToolRecoveryActionsFromRecords,
  runtimeToolRecoveryMissingRequiredFields,
  runtimeToolRecoveryRetryAction,
  type RuntimeToolRecoveryAction,
} from '../../runtime-shared/toolRecoveryActions';
import { runtimeToolRecoveryHintsFromRecords } from '../../runtime-shared/toolRecoveryHints';
import { useYachiyoTaskEventReplay } from '../hooks/useYachiyoTaskEventReplay';
import {
  yachiyoTaskApprovalStudioTarget,
  yachiyoTaskRunId,
  yachiyoTaskStudioRunId,
  yachiyoTaskStudioUrl,
} from '../taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot, PlannerTraceSummarySnapshot } from '../types';
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
      {timelineEvents.length || toolCallFacts.length ? (
        <ToolCallSummary events={timelineEvents} toolCalls={toolCallFacts} />
      ) : null}
      {permissionRecovery ? (
        <div
          className="yachiyo-agent-task-permission-recovery"
          data-desktop-tools={permissionRecovery.tools.join(',')}
          data-permission-targets={permissionRecovery.targets.join(',')}
          data-testid="yachiyo-agent-task-permission-recovery"
        >
          <UiIcon name="diagnostics" />
          <div>
            <strong>需要恢复桌面权限</strong>
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

type TaskPlannerSummarySnapshot = {
  approvals: string[];
  artifacts: string[];
  capabilities: string[];
  intentKind: string;
  missingCapabilities: string[];
  openQuestions: string[];
  routeToStudio: boolean | null;
  tools: string[];
};

function TaskPlannerSummary({ summary }: { summary: TaskPlannerSummarySnapshot }) {
  const chips = plannerSummaryChips(summary);
  return (
    <div
      className="yachiyo-agent-task-planner"
      data-intent-kind={summary.intentKind}
      data-plan-approvals={summary.approvals.join(',')}
      data-plan-artifacts={summary.artifacts.join(',')}
      data-plan-capabilities={summary.capabilities.join(',')}
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

function plannerSummaryFromTask(task: AgentTaskSnapshot): TaskPlannerSummarySnapshot | null {
  return plannerSummaryFromStructuredTrace(task.planner_summary)
    || plannerSummaryFromTaskMetadata(task.metadata);
}

function plannerSummaryFromStructuredTrace(
  value: PlannerTraceSummarySnapshot | null | undefined,
): TaskPlannerSummarySnapshot | null {
  const trace = objectValue(value);
  const intentKind = String(trace.intent_kind || '').trim();
  const tools = uniqueStrings([
    ...stringList(trace.plan_tools),
    ...stringList(trace.selected_tools),
  ]);
  const capabilities = uniqueStrings([
    ...stringList(trace.plan_capabilities),
    ...stringList(trace.required_capabilities),
  ]);
  const summary: TaskPlannerSummarySnapshot = {
    approvals: stringList(trace.approvals_required),
    artifacts: stringList(trace.artifacts_expected),
    capabilities,
    intentKind,
    missingCapabilities: stringList(trace.missing_capabilities),
    openQuestions: stringList(trace.open_questions),
    routeToStudio: booleanMetadataValue(trace.route_to_studio),
    tools,
  };
  return emptyPlannerSummary(summary) ? null : summary;
}

function plannerSummaryFromTaskMetadata(value: unknown): TaskPlannerSummarySnapshot | null {
  const metadata = objectValue(value);
  if (!booleanMetadataValue(metadata.yachiyo_runtime_planner)) return null;
  const intentKind = String(metadata.yachiyo_intent_kind || '').trim();
  const tools = stringList(metadata.yachiyo_plan_tools);
  const capabilities = uniqueStrings([
    ...stringList(metadata.yachiyo_plan_capabilities),
    ...stringList(metadata.yachiyo_required_capabilities),
  ]);
  const summary: TaskPlannerSummarySnapshot = {
    approvals: stringList(metadata.yachiyo_plan_approvals_required),
    artifacts: stringList(metadata.yachiyo_plan_artifacts_expected),
    capabilities,
    intentKind,
    missingCapabilities: stringList(metadata.yachiyo_missing_capabilities),
    openQuestions: stringList(metadata.yachiyo_plan_open_questions),
    routeToStudio: booleanMetadataValue(metadata.yachiyo_route_to_studio),
    tools,
  };
  return emptyPlannerSummary(summary) ? null : summary;
}

function emptyPlannerSummary(summary: TaskPlannerSummarySnapshot): boolean {
  return !summary.intentKind
    && !summary.tools.length
    && !summary.capabilities.length
    && !summary.approvals.length
    && !summary.artifacts.length
    && !summary.openQuestions.length
    && !summary.missingCapabilities.length;
}

function plannerSummaryDetail(summary: TaskPlannerSummarySnapshot): string {
  const parts = [
    summary.capabilities.length ? `${summary.capabilities.length} 个能力` : '',
    summary.tools.length ? `${summary.tools.length} 个工具` : '',
    summary.approvals.length ? `${summary.approvals.length} 个审批` : '',
    summary.artifacts.length ? `${summary.artifacts.length} 个产物` : '',
    summary.openQuestions.length ? `${summary.openQuestions.length} 个待确认` : '',
    summary.missingCapabilities.length ? `${summary.missingCapabilities.length} 个缺失能力` : '',
  ].filter(Boolean);
  return parts.join(' · ') || 'runtime plan';
}

function plannerSummaryChips(summary: TaskPlannerSummarySnapshot) {
  const chips = [
    ...summary.capabilities.slice(0, 3).map((value) => ({ kind: 'capability', label: '能力', value })),
    ...summary.tools.slice(0, 4).map((value) => ({ kind: 'tool', label: '工具', value })),
    ...summary.approvals.slice(0, 2).map((value) => ({ kind: 'approval', label: '审批', value })),
    ...summary.artifacts.slice(0, 2).map((value) => ({ kind: 'artifact', label: '产物', value })),
    ...summary.openQuestions.slice(0, 2).map((value) => ({ kind: 'question', label: '待确认', value })),
    ...summary.missingCapabilities.slice(0, 2).map((value) => ({ kind: 'missing', label: '缺失', value })),
  ];
  const visibleCount = chips.length;
  const totalCount = summary.capabilities.length
    + summary.tools.length
    + summary.approvals.length
    + summary.artifacts.length
    + summary.openQuestions.length
    + summary.missingCapabilities.length;
  if (totalCount > visibleCount) {
    chips.push({ kind: 'more', label: '更多', value: String(totalCount - visibleCount) });
  }
  return chips;
}

function booleanMetadataValue(value: unknown): boolean | null {
  if (typeof value === 'boolean') return value;
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'true') return true;
  if (normalized === 'false') return false;
  return null;
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
  href: string;
  hints: string[];
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
  const targets = uniqueStrings([
    ...safeEvents.flatMap((event) => permissionTargetsFromEvent(event)),
    ...safeToolCalls.flatMap((toolCall) => permissionTargetsFromToolCall(toolCall)),
  ]);
  if (!targets.length) return null;
  const hints = uniqueStrings([
    ...safeEvents.flatMap((event) => recoveryHintsFromEvent(event)),
    ...safeToolCalls.flatMap((toolCall) => recoveryHintsFromToolCall(toolCall)),
  ]);
  const tools = uniqueStrings([
    ...safeEvents.flatMap((event) => desktopToolsFromEvent(event)),
    ...safeToolCalls.flatMap((toolCall) => desktopToolsFromToolCall(toolCall)),
  ]);
  const actions = dedupeRecoveryActions([
    ...executableRecoveryActionsFromEvents(safeEvents),
    ...executableRecoveryActionsFromToolCalls(safeToolCalls),
  ]);
  const params = new URLSearchParams({
    command: 'native doctor',
    permission_targets: targets.join(','),
    return_to: 'chat',
  });
  if (tools.length) params.set('desktop_tools', tools.join(','));
  return {
    actions,
    href: `#/diagnostics?${params.toString()}`,
    hints,
    labels: targets.map((target) => permissionTargetLabels[target] || target),
    targets,
    tools,
  };
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
