import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  ArtifactSnapshot,
  PlannerTraceSummarySnapshot,
  ReplanRecoverySnapshot,
  RuntimeDebugSummarySnapshot,
  RuntimeExecutionEnvelopeSnapshot,
  TaskCoreSnapshot,
  TaskProgressSummarySnapshot,
  TaskStatus,
} from './types';
import {
  groupRunIdFromStudioUrl,
  runIdFromStudioUrl,
  studioRunRouteParams,
  studioRunUrl,
} from '../runtime-shared/studioLinks';

type YachiyoTaskChatParticipant = {
  id?: string;
  name?: string;
  nickname?: string;
};

type YachiyoTaskChatActivityEvent = {
  event_id?: string;
  tool_name?: string;
  phase?: string;
  title?: string;
  detail?: string;
  status?: string;
  created_at?: string;
  metadata?: {
    run_id?: string;
    workflow_run_id?: string;
  } & Record<string, unknown>;
};

type YachiyoTaskChatMetadata = {
  sender?: YachiyoTaskChatParticipant;
  run_id?: string;
  run_group_id?: string;
  group_dispatch_run_group_id?: string;
  run_status?: string;
  group_goal?: string;
  delegated_goal?: string;
  delegated_run_source_task_id?: string;
  pending_approval?: {
    approval_id?: string;
    tool?: string;
    input_preview?: unknown;
    requested_at?: string;
  };
  run_progress_title?: string;
  run_progress_detail?: string;
  run_artifacts?: Array<{ path?: string; kind?: string }>;
  workflow_run_id?: string;
  workflow_status?: string;
  workflow_waiting_child_run_id?: string;
  workflow_waiting_pending_approval?: {
    approval_id?: string;
    tool?: string;
    input_preview?: unknown;
    requested_at?: string;
  };
  planner_summary?: PlannerTraceSummarySnapshot | null;
  runtime_debug?: RuntimeDebugSummarySnapshot | null;
  yachiyo_runtime_debug?: RuntimeDebugSummarySnapshot | null;
  runtime_execution_envelope?: RuntimeExecutionEnvelopeSnapshot | null;
  yachiyo_execution_envelope?: RuntimeExecutionEnvelopeSnapshot | null;
  execution_envelope?: RuntimeExecutionEnvelopeSnapshot | null;
  task_core?: TaskCoreSnapshot | null;
  yachiyo_task_core?: TaskCoreSnapshot | null;
  planner_task_core?: TaskCoreSnapshot | null;
  task_progress?: TaskProgressSummarySnapshot | null;
  yachiyo_task_progress?: TaskProgressSummarySnapshot | null;
  replan_recoveries?: ReplanRecoverySnapshot[];
  yachiyo_replan_recoveries?: ReplanRecoverySnapshot[];
};

export type YachiyoTaskChatMessage = {
  role?: string;
  content?: string;
  text?: string;
  status?: string;
  created_at?: string;
  task_id?: string;
  progress_label?: string;
  activity_events?: YachiyoTaskChatActivityEvent[];
  metadata?: YachiyoTaskChatMetadata;
};

export function agentTaskHasVisibleExecution(
  task?: AgentTaskSnapshot | null,
  message?: YachiyoTaskChatMessage | null,
): boolean {
  if (message?.activity_events?.some(messageActivityHasVisibleExecution)) return true;
  if (!task) return false;
  if (task.tool_calls?.length) return true;
  if (task.pending_approvals?.length) return true;
  if (task.replan_recoveries?.length) return true;
  if (task.artifacts?.length) return true;
  if (taskRuntimeEnvelopeHasActionableRecovery(task)) return true;
  return Boolean(task.recent_events?.some(agentTaskEventHasToolEvidence));
}

export function agentTaskSnapshotFromMessage(
  message: YachiyoTaskChatMessage,
  displayContent: string,
): AgentTaskSnapshot | null {
  const runId = messageRunId(message);
  if ((message.role || '') !== 'assistant' || !runId) return null;
  const metadata = message.metadata || {};
  const groupRunId = messageGroupRunId(message);
  const senderName = participantDisplayName(metadata.sender);
  const title = String(
    metadata.run_progress_title
    || metadata.delegated_goal
    || metadata.group_goal
    || senderName
    || 'Yachiyo task',
  );
  const summary = compactStatusText(
    displayContent || message.content || message.text || metadata.run_progress_detail || '',
    140,
  );
  const pendingApprovals = messageTaskApprovals(message, runId, groupRunId) || [];
  const status = taskStatusFromRunStatus(messageRunStatus(message) || message.status || '');
  const runtimeExecutionEnvelope = messageRuntimeExecutionEnvelope(message);
  return {
    task_id: String(message.task_id || metadata.delegated_run_source_task_id || runId),
    conversation_id: null,
    title,
    status: pendingApprovals.length ? 'waiting_approval' : status,
    summary: summary || null,
    current_step: String(metadata.run_progress_detail || message.progress_label || '').trim() || null,
    progress_text: message.progress_label || null,
    needs_user_action: pendingApprovals.length > 0 || messageRunStatus(message) === 'approval_required',
    pending_approvals: pendingApprovals,
    recent_events: messageTaskEvents(message, runId),
    artifacts: messageTaskArtifacts(message, runId),
    metadata: { ...metadata },
    planner_summary: messagePlannerSummary(message),
    runtime_debug: messageRuntimeDebug(message),
    runtime_execution_envelope: runtimeExecutionEnvelope,
    task_core: messageTaskCore(message),
    task_progress: messageTaskProgress(message),
    replan_recoveries: messageReplanRecoveries(message),
    open_in_studio_url: studioRunUrl(runId, { groupRunId }),
    created_at: message.created_at || '',
    updated_at: message.created_at || '',
  };
}

export function publicTaskSnapshotForMessage(
  message: YachiyoTaskChatMessage,
  snapshotsById: Record<string, AgentTaskSnapshot>,
): AgentTaskSnapshot | null {
  const keys = uniqueStrings([
    message.task_id,
    message.metadata?.delegated_run_source_task_id,
    message.metadata?.workflow_waiting_child_run_id,
    messageRunId(message),
    messageGroupRunId(message),
  ]);
  for (const key of keys) {
    const snapshot = snapshotsById[key];
    if (snapshot) return snapshot;
  }
  return null;
}

export function yachiyoTaskCacheKeys(task: AgentTaskSnapshot): string[] {
  const artifactKeys = (task.artifacts || []).flatMap((artifact) => [
    artifact.run_id,
    artifact.source_run_id,
    artifact.workflow_run_id,
    artifact.group_run_id,
  ]);
  const approvalKeys = (task.pending_approvals || []).flatMap((approval) => [
    approval.run_id,
    approval.source_run_id,
    approval.workflow_run_id,
    approval.group_run_id,
  ]);
  return uniqueStrings([
    runIdFromStudioUrl(task.open_in_studio_url),
    groupRunIdFromStudioUrl(task.open_in_studio_url),
    task.task_id,
    ...((task.recent_events || []).map((event) => event.run_id)),
    ...approvalKeys,
    ...artifactKeys,
  ]);
}

export function yachiyoTaskRunId(task: AgentTaskSnapshot): string {
  const approvalRunKeys = (task.pending_approvals || []).flatMap((approval) => [
    approval.run_id,
    approval.source_run_id,
    approval.workflow_run_id,
  ]);
  const artifactRunKeys = (task.artifacts || []).flatMap((artifact) => [
    artifact.run_id,
    artifact.source_run_id,
    artifact.workflow_run_id,
  ]);
  return uniqueStrings([
    runIdFromStudioUrl(task.open_in_studio_url),
    ...(task.recent_events || []).map((event) => event.run_id),
    ...approvalRunKeys,
    ...artifactRunKeys,
    task.task_id,
  ])[0] || '';
}

export function yachiyoTaskStudioUrl(task: AgentTaskSnapshot): string {
  const publicUrl = String(task.open_in_studio_url || '').trim();
  if (publicUrl) return publicUrl;
  return studioRunUrl(yachiyoTaskRunId(task)) || '';
}

export function yachiyoTaskStudioRunId(task: AgentTaskSnapshot): string {
  return runIdFromStudioUrl(yachiyoTaskStudioUrl(task)) || yachiyoTaskRunId(task);
}

export function yachiyoTaskStudioGroupRunId(task: AgentTaskSnapshot): string {
  return groupRunIdFromStudioUrl(yachiyoTaskStudioUrl(task));
}

export function yachiyoTaskStudioTarget(
  task: AgentTaskSnapshot,
  studioUrlOverride = '',
): {
  groupRunId: string;
  routeParams: Record<string, string> | null;
  runId: string;
  studioUrl: string;
} {
  const runId = yachiyoTaskStudioRunId(task);
  const groupRunId = yachiyoTaskStudioGroupRunId(task);
  const studioUrl = String(studioUrlOverride || '').trim() || yachiyoTaskStudioUrl(task);
  return {
    groupRunId,
    routeParams: studioRunRouteParams(runId, { groupRunId, studioUrl }),
    runId,
    studioUrl,
  };
}

export function yachiyoTaskApprovalStudioTarget(
  task: AgentTaskSnapshot,
  approval: ApprovalCardSnapshot,
): { runId: string; studioUrl: string } {
  const publicUrl = String(approval.open_in_studio_url || '').trim();
  const runId = uniqueStrings([
    runIdFromStudioUrl(publicUrl),
    approval.source_run_id,
    approval.run_id,
    approval.workflow_run_id,
  ])[0] || '';
  const studioUrl = publicUrl || (runId
    ? studioRunUrl(runId, {
      groupRunId: String(approval.group_run_id || '').trim() || yachiyoTaskStudioGroupRunId(task),
    }) || ''
    : '');
  return { runId, studioUrl };
}

export function yachiyoTaskArtifactReadTarget(
  artifact: ArtifactSnapshot,
  taskId = '',
): { path: string; runId: string; taskId: string } {
  return {
    path: String(artifact.path || '').trim(),
    runId: uniqueStrings([
      artifact.source_run_id,
      artifact.run_id,
      artifact.workflow_run_id,
    ])[0] || '',
    taskId: String(taskId || '').trim(),
  };
}

export function yachiyoTaskStatusMessage(
  task: AgentTaskSnapshot,
  action: 'approve' | 'reject' | 'cancel',
): string {
  if (action === 'cancel') {
    if (task.status === 'cancelled') return 'Agent 任务已取消。';
    if (task.status === 'failed') return 'Agent 任务取消失败。';
    return '已请求取消 Agent 任务。';
  }
  if (task.status === 'waiting_approval') return 'Agent 任务需要处理下一次审批。';
  if (task.status === 'running' || task.status === 'queued') {
    return action === 'approve'
      ? '已批准，Agent 任务正在继续执行...'
      : '已拒绝，Agent 任务正在整理结果...';
  }
  if (task.status === 'completed') return 'Agent 任务已完成。';
  if (task.status === 'failed') return 'Agent 任务失败。';
  if (task.status === 'cancelled') return 'Agent 任务已取消。';
  return task.progress_text || task.current_step || 'Agent 任务状态已更新。';
}

function taskStatusFromRunStatus(status: string): TaskStatus {
  const normalized = normalizeRunStatus(status);
  if (normalized === 'approval_required') return 'waiting_approval';
  if (normalized === 'processing' || normalized === 'running' || normalized === 'pending') return 'running';
  if (normalized === 'completed') return 'completed';
  if (normalized === 'failed' || normalized === 'error') return 'failed';
  if (normalized === 'cancelled' || normalized === 'canceled') return 'cancelled';
  return 'running';
}

function messageTaskApprovals(
  message: YachiyoTaskChatMessage,
  runId: string,
  groupRunId = '',
): AgentTaskSnapshot['pending_approvals'] {
  const approvals: AgentTaskSnapshot['pending_approvals'] = [];
  const pending = message.metadata?.pending_approval;
  if (pending) {
    const tool = String(pending.tool || 'tool');
    approvals.push({
      approval_id: String(pending.approval_id || '').trim(),
      run_id: runId,
      title: `审批 ${tool}`,
      status: 'pending',
      tool_name: tool,
      input_preview: recordPreview(pending.input_preview),
      requested_at: pending.requested_at || '',
      open_in_studio_url: studioRunUrl(runId, { groupRunId }),
    });
  }
  const workflowPending = message.metadata?.workflow_waiting_pending_approval;
  if (workflowPending) {
    const childRunId = String(message.metadata?.workflow_waiting_child_run_id || runId);
    const tool = String(workflowPending.tool || 'workflow.approval');
    approvals.push({
      approval_id: String(workflowPending.approval_id || '').trim(),
      run_id: childRunId,
      title: `审批 ${tool}`,
      status: 'pending',
      tool_name: tool,
      input_preview: recordPreview(workflowPending.input_preview),
      requested_at: workflowPending.requested_at || '',
      open_in_studio_url: studioRunUrl(childRunId, { groupRunId }),
    });
  }
  return approvals;
}

function messageTaskArtifacts(
  message: YachiyoTaskChatMessage,
  runId: string,
): AgentTaskSnapshot['artifacts'] {
  return (message.metadata?.run_artifacts || []).map((artifact, index) => {
    const path = String(artifact.path || '').trim();
    const kind = String(artifact.kind || 'artifact').trim();
    return {
      artifact_id: `${runId}:${path || kind}:${index}`,
      run_id: runId,
      source_run_id: runId,
      title: path || kind,
      kind,
      path: path || null,
    };
  });
}

function messageTaskEvents(
  message: YachiyoTaskChatMessage,
  runId: string,
): AgentTaskSnapshot['recent_events'] {
  return (message.activity_events || []).slice(0, 3).map((event, index) => ({
    event_id: event.event_id || null,
    run_id: activityRunId(event) || runId,
    sequence: index + 1,
    schema_version: 1,
    event_type: event.phase || event.status || 'chat.activity',
    title: event.title || event.tool_name || null,
    detail: event.detail || null,
    visibility: 'user',
    sensitivity: 'public',
    payload: {
      ...(event.metadata || {}),
      tool_name: event.tool_name || undefined,
    },
    created_at: event.created_at || '',
  }));
}

function agentTaskEventHasToolEvidence(
  event: NonNullable<AgentTaskSnapshot['recent_events']>[number],
): boolean {
  const eventType = String(event.event_type || '').trim().toLowerCase();
  if (eventType.startsWith('agent.tool.') || eventType.startsWith('tool.')) return true;
  if (eventTypeHasActionableRecovery(eventType)) return true;
  const actor = String(event.actor || '').trim().toLowerCase();
  if (actor === 'tool' || actor.startsWith('tool:')) return true;
  const payload = event.payload || {};
  if (Boolean(
    String(payload.tool_name || '').trim()
    || String(payload.tool_call_id || '').trim()
    || String(payload.tool || '').trim(),
  )) return true;
  return recordHasActionableRecoveryEvidence(payload);
}

function messageActivityHasVisibleExecution(event: YachiyoTaskChatActivityEvent): boolean {
  if (String(event.tool_name || '').trim()) return true;
  const eventTypes = [event.phase, event.status]
    .map((value) => String(value || '').trim().toLowerCase())
    .filter(Boolean);
  if (eventTypes.some((eventType) => (
    eventType.startsWith('agent.tool.')
    || eventType.startsWith('tool.')
    || eventTypeHasActionableRecovery(eventType)
  ))) return true;
  return recordHasActionableRecoveryEvidence(event.metadata || {});
}

function eventTypeHasActionableRecovery(eventType: string): boolean {
  return eventType.includes('permission_recovery')
    || eventType.includes('intent_unavailable')
    || eventType.includes('intent_unverified')
    || eventType.includes('.replan.recovery.')
    || eventType.includes('recovery_required')
    || eventType.includes('retry_required');
}

function taskRuntimeEnvelopeHasActionableRecovery(task: AgentTaskSnapshot): boolean {
  const allowPlannedRetries = (
    task.task_progress?.needs_replan === true
    || Number(task.task_progress?.failed_verification_count || 0) > 0
  );
  return Boolean(task.runtime_execution_envelope?.requests?.some((request) => {
    const retry = objectRecord(request.observation_retry);
    if (!Object.keys(retry).length) return false;
    const evidence = objectRecord(request.observation_evidence);
    return allowPlannedRetries || runtimeExecutionEvidenceNeedsRetry(evidence);
  }));
}

function runtimeExecutionEvidenceNeedsRetry(evidence: Record<string, unknown>): boolean {
  if (recordHasActionableRecoveryEvidence(evidence)) return true;
  if (evidence.verification_failed === true) return true;
  if (evidence.foreground_required === true && evidence.foreground_ready === false) return true;
  return false;
}

function recordHasActionableRecoveryEvidence(value: unknown): boolean {
  const record = objectRecord(value);
  const result = objectRecord(record.result);
  const data = objectRecord(record.data);
  return [record, result, data].some((source) => (
    source.permission_error === true
    || unknownValueHasEntries(source.permission_targets)
    || unknownValueHasEntries(source.missing_permissions)
    || unknownValueHasEntries(source.blocking_condition)
    || unknownValueHasEntries(source.blocking_conditions)
    || unknownValueHasEntries(source.recovery_actions)
    || unknownValueHasEntries(source.observation_retry)
  ));
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function unknownValueHasEntries(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => unknownValueHasEntries(item));
  if (value && typeof value === 'object') return Object.keys(value).length > 0;
  return typeof value === 'string' ? Boolean(value.trim()) : value === true;
}

function messageRunStatus(message?: YachiyoTaskChatMessage | null) {
  return normalizeRunStatus(message?.metadata?.run_status || message?.metadata?.workflow_status || '');
}

function messageRunId(message?: YachiyoTaskChatMessage | null) {
  return String(message?.metadata?.run_id || message?.metadata?.workflow_run_id || '').trim();
}

function messageGroupRunId(message?: YachiyoTaskChatMessage | null) {
  return String(message?.metadata?.run_group_id || message?.metadata?.group_dispatch_run_group_id || '').trim();
}

function activityRunId(event?: YachiyoTaskChatActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
}

function messagePlannerSummary(message?: YachiyoTaskChatMessage | null): PlannerTraceSummarySnapshot | null {
  const value = message?.metadata?.planner_summary;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value;
}

function messageRuntimeDebug(message?: YachiyoTaskChatMessage | null): RuntimeDebugSummarySnapshot | null {
  return messageObjectMetadataValue<RuntimeDebugSummarySnapshot>(
    message,
    ['runtime_debug', 'yachiyo_runtime_debug'],
  );
}

function messageRuntimeExecutionEnvelope(
  message?: YachiyoTaskChatMessage | null,
): RuntimeExecutionEnvelopeSnapshot | null {
  return messageObjectMetadataValue<RuntimeExecutionEnvelopeSnapshot>(
    message,
    ['runtime_execution_envelope', 'yachiyo_execution_envelope', 'execution_envelope'],
  );
}

function messageTaskCore(message?: YachiyoTaskChatMessage | null): TaskCoreSnapshot | null {
  return messageObjectMetadataValue<TaskCoreSnapshot>(
    message,
    ['task_core', 'yachiyo_task_core', 'planner_task_core'],
  );
}

function messageTaskProgress(message?: YachiyoTaskChatMessage | null): TaskProgressSummarySnapshot | null {
  return messageObjectMetadataValue<TaskProgressSummarySnapshot>(
    message,
    ['task_progress', 'yachiyo_task_progress'],
  );
}

function messageReplanRecoveries(message?: YachiyoTaskChatMessage | null): ReplanRecoverySnapshot[] {
  return messageArrayMetadataValue<ReplanRecoverySnapshot>(
    message,
    ['replan_recoveries', 'yachiyo_replan_recoveries'],
  );
}

function messageObjectMetadataValue<T>(
  message: YachiyoTaskChatMessage | null | undefined,
  keys: string[],
): T | null {
  const metadata = message?.metadata;
  if (!metadata) return null;
  const record = metadata as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as T;
  }
  return null;
}

function messageArrayMetadataValue<T>(
  message: YachiyoTaskChatMessage | null | undefined,
  keys: string[],
): T[] {
  const metadata = message?.metadata;
  if (!metadata) return [];
  const record = metadata as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) return value.filter((item) => item && typeof item === 'object') as T[];
  }
  return [];
}

function participantDisplayName(participant?: YachiyoTaskChatParticipant | null) {
  return String(participant?.nickname || participant?.name || participant?.id || '').trim();
}

function compactStatusText(text: string, maxLength = 96) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '任务执行失败';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

function normalizeRunStatus(status?: string) {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)));
}

function recordPreview(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}
