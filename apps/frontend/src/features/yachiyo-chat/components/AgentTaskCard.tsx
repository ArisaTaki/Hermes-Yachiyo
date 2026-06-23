import { UiIcon } from '../../../components/UiIcon';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { runtimeToolRecoveryHintsFromRecords } from '../../runtime-shared/toolRecoveryHints';
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
  const canCancel = onCancelTask && ['queued', 'running', 'waiting_approval'].includes(status);
  const hasHeaderActions = Boolean((studioRunId && studioUrl && onOpenStudio) || canCancel);
  const permissionRecovery = taskPermissionRecoveryFromEvents(timelineEvents);

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
                {permissionRecovery.actions.slice(0, 3).map((action) => (
                  <button
                    type="button"
                    data-permission-target={action.permission_target}
                    data-recovery-tool={action.tool}
                    data-testid="yachiyo-agent-task-run-recovery-action"
                    disabled={busy || !onRunRecoveryAction}
                    key={`${action.tool}:${action.prompt}:${action.permission_target}`}
                    onClick={() => void onRunRecoveryAction?.(task, action)}
                    title={action.prompt}
                  >
                    <UiIcon name="settings" />
                    <span>{action.label}</span>
                  </button>
                ))}
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

type TaskPermissionRecovery = {
  actions: TaskPermissionRecoveryAction[];
  href: string;
  hints: string[];
  labels: string[];
  targets: string[];
  tools: string[];
};

export type TaskPermissionRecoveryAction = {
  input: Record<string, unknown>;
  label: string;
  permission_target: string;
  prompt: string;
  risk_level?: string;
  tool: string;
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

export function taskPermissionRecoveryFromEvents(events: AgentTaskSnapshot['recent_events']): TaskPermissionRecovery | null {
  const targets = uniqueStrings((events || []).flatMap((event) => permissionTargetsFromEvent(event)));
  if (!targets.length) return null;
  const hints = uniqueStrings((events || []).flatMap((event) => recoveryHintsFromEvent(event)));
  const tools = uniqueStrings((events || []).flatMap((event) => desktopToolsFromEvent(event)));
  const actions = executableRecoveryActionsFromEvents(events || []);
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
  const byKey = new Map<string, TaskPermissionRecoveryAction>();
  (events || []).flatMap((event) => recoveryActionsFromEvent(event)).forEach((action) => {
    const key = `${action.tool}:${JSON.stringify(action.input)}:${action.permission_target}`;
    if (!byKey.has(key)) byKey.set(key, action);
  });
  return Array.from(byKey.values());
}

function recoveryActionsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): TaskPermissionRecoveryAction[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  return [result, payload].filter(Boolean).flatMap((source) => recoveryActionsFromRecord(source));
}

function recoveryActionsFromRecord(source: Record<string, unknown>): TaskPermissionRecoveryAction[] {
  const rawActions = Array.isArray(source.recovery_actions) ? source.recovery_actions : [];
  return rawActions.flatMap((rawAction) => {
    const action = objectValue(rawAction);
    const tool = String(action.tool || '').trim();
    const input = objectValue(action.input);
    if (tool !== 'app.open') return [];
    const appName = String(input.app_name || '').trim();
    if (!appName) return [];
    const label = String(action.label || appName || tool).trim();
    return [{
      input,
      label,
      permission_target: String(action.permission_target || '').trim(),
      prompt: label || `打开 ${appName}`,
      risk_level: String(action.risk_level || '').trim() || undefined,
      tool,
    }];
  });
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

function recoveryHintsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const sources = [result, payload].filter(Boolean);
  return runtimeToolRecoveryHintsFromRecords(sources);
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
