import type { AgentTaskSnapshot, TaskStatus } from './types';
import { groupRunIdFromStudioUrl, runIdFromStudioUrl, studioRunUrl } from '../runtime-shared/studioLinks';

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
  ]);
  return uniqueStrings([
    runIdFromStudioUrl(task.open_in_studio_url),
    groupRunIdFromStudioUrl(task.open_in_studio_url),
    task.task_id,
    ...((task.recent_events || []).map((event) => event.run_id)),
    ...((task.pending_approvals || []).map((approval) => approval.run_id || '')),
    ...artifactKeys,
  ]);
}

export function yachiyoTaskRunId(task: AgentTaskSnapshot): string {
  const artifactRun = (task.artifacts || []).find((artifact) => artifact.run_id || artifact.source_run_id);
  return uniqueStrings([
    runIdFromStudioUrl(task.open_in_studio_url),
    ...(task.recent_events || []).map((event) => event.run_id),
    ...(task.pending_approvals || []).map((approval) => approval.run_id || ''),
    artifactRun?.run_id,
    artifactRun?.source_run_id,
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
      approval_id: String(pending.approval_id || runId),
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
      approval_id: String(workflowPending.approval_id || childRunId),
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
    payload: event.metadata || {},
    created_at: event.created_at || '',
  }));
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
