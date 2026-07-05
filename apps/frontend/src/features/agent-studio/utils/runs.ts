import type {
  AgentSpec,
  RunnableSummary,
  RunGroupSpec,
  RunSpec,
  WorkflowSpec,
} from '../types';
import type {
  ApprovalCardSnapshot,
  ArtifactSnapshot,
  GroupRunSnapshot,
  PublicRunEvent,
  RunTimelineSnapshot,
  YachiyoGroupRunSnapshot,
  YachiyoRunTimelineSnapshot,
} from '../../yachiyo-studio/types';

import {
  agentCapabilityLine,
  runnableCapabilityLine,
} from './agents';
import { publicRunEventPayloadDetail, publicRunEventWorkflowStepPayload } from './runTimeline';

export type RunKindFilter = 'all' | 'workflow' | 'agent';
export type RunStatusFilter = 'all' | 'completed' | 'failed' | 'active';

type PublicRunTimelineRunSpecFallback = {
  kind?: RunSpec['kind'];
  runnableId?: string;
  runnableName?: string;
  userGoal?: string;
};

type PublicRunTimelineRunSpecOptions = PublicRunTimelineRunSpecFallback & {
  allowLegacyFields?: boolean;
};

export type RunHistoryGroup = {
  key: string;
  label: string;
  subtitle: string;
  avatarUrl?: string;
  runs: RunSpec[];
};

export function normalizeRunStatus(status: string): string {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

export function isActiveRunStatus(status: string): boolean {
  return ['processing', 'pending', 'approval_required'].includes(normalizeRunStatus(status));
}

function approvalInputSignature(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function runApprovalSignature(run: RunSpec | null | undefined): string {
  const pending = run?.pending_approval;
  if (!pending) return '';
  const approvalId = String(pending.approval_id || '').trim();
  if (approvalId) return `id:${approvalId}`;
  return [
    String(pending.tool || '').trim(),
    approvalInputSignature(pending.input_preview),
  ].join('\n');
}

export function makeRunContinuingAfterApproval(run: RunSpec, result: string): RunSpec {
  const nextRun: RunSpec = { ...run };
  delete nextRun.pending_approval;
  return {
    ...nextRun,
    status: 'processing',
    result,
    updated_at: new Date().toISOString(),
  };
}

export function approvedRunStatusMessage(run: RunSpec): string {
  const status = normalizeRunStatus(run.status);
  if (status === 'processing') return '已批准，Run 正在继续执行。';
  if (status === 'approval_required') return '已批准，Run 需要继续处理下一次审批。';
  if (status === 'completed') return '已批准，Run 已完成。';
  if (status === 'failed') return '已批准，但 Run 执行失败。';
  return '已批准，Run 状态已更新。';
}

export function publicRunTimelineToRunSpec(
  snapshot: RunTimelineSnapshot | YachiyoRunTimelineSnapshot,
  fallback: PublicRunTimelineRunSpecOptions = {},
): RunSpec {
  const allowLegacyFields = fallback.allowLegacyFields !== false;
  const agentId = String(snapshot.agent_id || '').trim();
  const workflowRunId = String(snapshot.workflow_run_id || '').trim();
  const parentRunId = String(snapshot.parent_run_id || '').trim();
  const hasWorkflowDefinition = 'workflow_id' in snapshot && Boolean(snapshot.workflow_id);
  const workflowChildParentRunId = parentRunId || (workflowRunId && workflowRunId !== snapshot.run_id ? workflowRunId : '');
  const inferredKind = agentId ? 'agent_run' : (workflowRunId || hasWorkflowDefinition ? 'workflow_run' : 'agent_run');
  const snapshotKind = 'kind' in snapshot ? String((snapshot as { kind?: string }).kind || '').trim() : '';
  const kind = fallback.kind || snapshotKind || inferredKind;
  const pendingApproval = snapshot.pending_approval || snapshot.approvals?.find(
    (approval) => approval.status === 'pending',
  );
  const workflowId = 'workflow_id' in snapshot ? String(snapshot.workflow_id || '').trim() : '';
  const workflowObjective = 'objective' in snapshot ? String(snapshot.objective || '').trim() : '';
  const currentNodeId = 'current_node_id' in snapshot ? String(snapshot.current_node_id || '').trim() : '';
  const currentNodeLabel = 'current_node_label' in snapshot ? String(snapshot.current_node_label || '').trim() : '';
  const finalAnswer = 'final_answer' in snapshot ? String(snapshot.final_answer || '').trim() : '';
  const legacyResult = allowLegacyFields && 'result' in snapshot ? String((snapshot as { result?: string }).result || '').trim() : '';
  const legacyRunnableName = allowLegacyFields && 'runnable_name' in snapshot ? String((snapshot as { runnable_name?: string }).runnable_name || '').trim() : '';
  const legacyUserGoal = allowLegacyFields && 'user_goal' in snapshot ? String((snapshot as { user_goal?: string }).user_goal || '').trim() : '';
  return {
    run_id: snapshot.run_id,
    parent_run_id: parentRunId || undefined,
    run_group_id: snapshot.run_group_id || snapshot.group_run_id || undefined,
    run_group_source: kind === 'workflow_run' || workflowChildParentRunId ? 'workflow' : undefined,
    task_id: 'task_id' in snapshot ? snapshot.task_id || undefined : undefined,
    session_id: 'session_id' in snapshot ? snapshot.session_id || undefined : undefined,
    task_run_link_created_at: 'task_run_link_created_at' in snapshot
      ? snapshot.task_run_link_created_at || undefined
      : undefined,
    task_run_link_updated_at: 'task_run_link_updated_at' in snapshot
      ? snapshot.task_run_link_updated_at || undefined
      : undefined,
    task_run_link_run_status: 'task_run_link_run_status' in snapshot
      ? snapshot.task_run_link_run_status || undefined
      : undefined,
    task_run_link_last_event_sequence: 'task_run_link_last_event_sequence' in snapshot
      ? snapshot.task_run_link_last_event_sequence ?? undefined
      : undefined,
    rerun_of_run_id: snapshot.rerun_of_run_id || undefined,
    rerun_of_kind: snapshot.rerun_of_kind || undefined,
    rerun_of_status: snapshot.rerun_of_status || undefined,
    rerun_of_runnable_id: snapshot.rerun_of_runnable_id || undefined,
    rerun_of_runnable_name: snapshot.rerun_of_runnable_name || undefined,
    rerun_original_created_at: snapshot.rerun_original_created_at || undefined,
    rerun_original_updated_at: snapshot.rerun_original_updated_at || undefined,
    recovery_source: snapshot.recovery_source || undefined,
    kind,
    runnable_id: fallback.runnableId || (kind === 'workflow_run' ? workflowId || workflowRunId : agentId) || snapshot.run_id,
    runnable_name: snapshot.title || legacyRunnableName || fallback.runnableName || undefined,
    status: snapshot.status || 'processing',
    user_goal: (fallback.userGoal ?? workflowObjective) || legacyUserGoal || snapshot.title || '',
    result: finalAnswer || legacyResult || undefined,
    runtime_debug: snapshot.runtime_debug || undefined,
    runtime_execution_envelope: snapshot.runtime_execution_envelope || undefined,
    task_core: snapshot.task_core || undefined,
    task_progress: snapshot.task_progress || undefined,
    replan_recoveries: snapshot.replan_recoveries || [],
    timeline: (snapshot.events || []).map(publicRunEventToTimelineEvent),
    artifacts: publicArtifactsOrLegacy(snapshot.artifacts, undefined),
    pending_approval: pendingApproval
      ? publicApprovalToRunPendingApproval(pendingApproval) || undefined
      : undefined,
    created_at: snapshot.created_at,
    updated_at: snapshot.updated_at,
    agent_run_id: kind === 'agent_run' ? snapshot.run_id : undefined,
    workflow_id: workflowId || undefined,
    workflow_run_id: workflowRunId || (kind === 'workflow_run' ? snapshot.run_id : undefined),
    objective: workflowObjective || undefined,
    current_node_id: currentNodeId || undefined,
    current_node_label: currentNodeLabel || undefined,
    final_answer: finalAnswer || legacyResult || undefined,
  };
}

export function publicRunTimelineToStudioRunSpec(
  snapshot: RunTimelineSnapshot | YachiyoRunTimelineSnapshot,
  fallback: PublicRunTimelineRunSpecFallback = {},
): RunSpec {
  return publicRunTimelineToRunSpec(snapshot, {
    ...fallback,
    allowLegacyFields: false,
  });
}

export function publicGroupRunToRunGroupSpec(
  snapshot: GroupRunSnapshot | YachiyoGroupRunSnapshot,
): RunGroupSpec {
  const childRunIds = snapshot.child_run_ids?.length
    ? snapshot.child_run_ids
    : (snapshot.runs || []).map((run) => run.run_id).filter(Boolean);
  return {
    run_group_id: snapshot.run_group_id || snapshot.group_run_id,
    group_id: snapshot.group_id || undefined,
    title: snapshot.title || snapshot.objective || 'Group run',
    source: 'yachiyo_studio',
    status: snapshot.status || 'unknown',
    objective: snapshot.objective || undefined,
    summary: snapshot.final_answer || snapshot.objective || '',
    participants: snapshot.participants || [],
    events: snapshot.events || [],
    pending_approvals: snapshot.pending_approvals || [],
    shared_artifacts: snapshot.shared_artifacts || [],
    planner_summary: snapshot.planner_summary || undefined,
    runtime_debug: snapshot.runtime_debug || undefined,
    runtime_execution_envelope: snapshot.runtime_execution_envelope || undefined,
    task_core: snapshot.task_core || undefined,
    task_progress: snapshot.task_progress || undefined,
    replan_recoveries: snapshot.replan_recoveries || [],
    final_answer: snapshot.final_answer || undefined,
    child_run_ids: childRunIds,
    created_at: snapshot.created_at,
    updated_at: snapshot.updated_at,
  };
}

export function runStatusLabel(status: string): string {
  const normalized = normalizeRunStatus(status);
  if (normalized === 'completed') return '已完成';
  if (normalized === 'failed') return '执行失败';
  if (normalized === 'cancelled') return '已取消';
  if (normalized === 'approval_required') return '等待审批';
  if (normalized === 'processing') return '进行中';
  if (normalized === 'pending') return '等待中';
  return normalized || '未知状态';
}

export function runStatusTone(status: string): string {
  const normalized = normalizeRunStatus(status);
  if (normalized === 'completed') return 'ready';
  if (normalized === 'failed' || normalized === 'cancelled') return 'danger';
  if (normalized === 'approval_required') return 'approval';
  return 'running';
}

export function runKindLabel(kind: string): string {
  if (kind === 'agent_run') return 'Agent Run';
  if (kind === 'workflow_run') return 'Workflow Run';
  return kind || 'Run';
}

function runHistoryGroupKindLabel(run: RunSpec): string {
  if (run.kind === 'agent_run') return 'Agent';
  if (run.kind === 'workflow_run') return 'Workflow';
  return runKindLabel(run.kind);
}

export function runHistoryGroupKey(run: RunSpec): string {
  if (run.kind === 'agent_run') return `agent:${run.runnable_id || run.runnable_name || 'unknown'}`;
  if (run.kind === 'workflow_run') return `workflow:${run.runnable_id || run.runnable_name || 'unknown'}`;
  return `${run.kind || 'run'}:${run.runnable_id || run.runnable_name || 'unknown'}`;
}

export function runHistoryGroupSummary(runs: RunSpec[]): string {
  const failed = runs.filter((run) => ['failed', 'cancelled'].includes(normalizeRunStatus(run.status))).length;
  const active = runs.filter((run) => isActiveRunStatus(run.status)).length;
  const completed = runs.filter((run) => normalizeRunStatus(run.status) === 'completed').length;
  const parts = [
    active ? `${active} active` : '',
    failed ? `${failed} failed` : '',
    completed ? `${completed} done` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : `${runs.length} runs`;
}

export function runUpdatedTimestamp(run?: RunSpec): number {
  const timestamp = Date.parse(run?.updated_at || run?.created_at || '');
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function runHistoryGroupsFor(runs: RunSpec[], runnables: RunnableSummary[], agents: AgentSpec[]): RunHistoryGroup[] {
  const runnableById = new Map(runnables.map((runnable) => [runnable.id, runnable]));
  const agentById = new Map(agents.map((agent) => [agent.agent_id, agent]));
  const groups = new Map<string, RunHistoryGroup>();
  runs.forEach((run) => {
    const key = runHistoryGroupKey(run);
    const runnable = runnableById.get(run.runnable_id);
    const agent = agentById.get(run.runnable_id);
    const label = run.runnable_name || runnable?.nickname || runnable?.name || agent?.nickname || agent?.name || run.runnable_id || runKindLabel(run.kind);
    const existing = groups.get(key);
    if (existing) {
      existing.runs.push(run);
      return;
    }
    groups.set(key, {
      key,
      label,
      subtitle: runHistoryGroupKindLabel(run),
      avatarUrl: runnable?.avatar_url || agent?.avatar_url,
      runs: [run],
    });
  });
  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      runs: [...group.runs].sort((a, b) => runUpdatedTimestamp(b) - runUpdatedTimestamp(a)),
    }))
    .sort((a, b) => runUpdatedTimestamp(b.runs[0]) - runUpdatedTimestamp(a.runs[0]));
}

export function isWorkflowChildAgentRun(run: RunSpec): boolean {
  return run.kind === 'agent_run' && run.run_group_source === 'workflow';
}

export function isPotentialWorkflowChildAgentRun(run: RunSpec | null): run is RunSpec {
  return Boolean(run && run.kind === 'agent_run' && run.run_group_id);
}

export function runMatchesFilter(run: RunSpec, filter: RunKindFilter): boolean {
  if (isWorkflowChildAgentRun(run)) return false;
  if (filter === 'agent') return run.kind === 'agent_run';
  if (filter === 'workflow') return run.kind === 'workflow_run';
  return true;
}

export function runMatchesStatusFilter(run: RunSpec, filter: RunStatusFilter): boolean {
  const status = normalizeRunStatus(run.status);
  if (filter === 'completed') return status === 'completed';
  if (filter === 'failed') return status === 'failed' || status === 'cancelled';
  if (filter === 'active') return isActiveRunStatus(status);
  return true;
}

function compactSearchText(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
}

function runSearchHaystack(run: RunSpec, extraText = ''): string {
  const timelineText = (run.timeline || [])
    .map((event) => compactSearchText(event))
    .join(' ');
  const artifactText = (run.artifacts || [])
    .map((artifact) => compactSearchText(artifact))
    .join(' ');
  return [
    run.run_id,
    run.run_group_id,
    run.run_group_source,
    run.kind,
    run.runnable_id,
    run.runnable_name,
    run.status,
    runStatusLabel(run.status),
    runKindLabel(run.kind),
    run.user_goal,
    run.result,
    run.runtime_debug,
    timelineText,
    artifactText,
    extraText,
  ].map(compactSearchText).join(' ').toLowerCase();
}

export function runMatchesSearch(run: RunSpec, query: string, extraText = ''): boolean {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (!terms.length) return true;
  const haystack = runSearchHaystack(run, extraText);
  return terms.every((term) => haystack.includes(term));
}

export function runSearchTextByRunnableIdFor(
  runnables: RunnableSummary[],
  agents: AgentSpec[],
  workflows: WorkflowSpec[],
): Map<string, string> {
  const next = new Map<string, string>();
  const append = (id: string, parts: unknown[]) => {
    const key = String(id || '').trim();
    if (!key) return;
    next.set(key, [next.get(key) || '', ...parts.map(compactSearchText)].join(' '));
  };
  runnables.forEach((item) => {
    append(item.id, [
      item.kind,
      item.name,
      item.nickname,
      item.description,
      item.category,
      item.output_contract,
      item.enabled === false ? 'disabled 停用' : 'enabled 启用',
      runnableCapabilityLine(item),
    ]);
  });
  agents.forEach((agent) => {
    append(agent.agent_id, [
      'agent',
      agent.name,
      agent.nickname,
      agent.description,
      agent.category,
      agent.output_contract,
      agent.enabled === false ? 'disabled 停用' : 'enabled 启用',
      agentCapabilityLine(agent),
    ]);
  });
  workflows.forEach((workflow) => {
    append(workflow.workflow_id, [
      'workflow',
      workflow.name,
      workflow.description,
      workflow.enabled === false ? 'disabled 停用' : 'enabled 启用',
    ]);
  });
  return next;
}

export function formatRunDate(value?: string): string {
  if (!value) return '未知时间';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}

export function publicRunEventToTimelineEvent(event: PublicRunEvent): Record<string, unknown> {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const detail = publicRunEventPayloadDetail(event);
  return {
    event_id: event.event_id || '',
    run_id: event.run_id,
    schema_version: event.schema_version || '',
    event: event.event_type,
    actor: event.actor || '',
    visibility: event.visibility || '',
    sensitivity: event.sensitivity || '',
    detail,
    status: typeof payload.status === 'string' ? payload.status : '',
    time: event.created_at || '',
    sequence: event.sequence,
    input_preview: payload.input_preview,
    result: payload.result || payload.content || payload.error || '',
    pending_approval: payload.pending_approval || payload.approval || null,
    child_run_id: payload.child_run_id,
    workflow_node_id: payload.workflow_node_id,
    workflow_node_kind: payload.workflow_node_kind,
    workflow_node_label: payload.workflow_node_label,
    ...publicRunEventWorkflowStepPayload(payload),
    payload,
  };
}

export function publicApprovalToRunPendingApproval(approval: ApprovalCardSnapshot | null) {
  if (!approval) return null;
  const legacyTool = 'tool' in approval ? String((approval as { tool?: string }).tool || '').trim() : '';
  return {
    approval_id: approval.approval_id,
    input_preview: approval.input_preview || {},
    open_in_studio_url: approval.open_in_studio_url || '',
    policy_reason: approval.policy_reason || '',
    planning_reason: approval.planning_reason || '',
    decision_id: approval.decision_id || '',
    plan_id: approval.plan_id || '',
    tool_plan_id: approval.tool_plan_id || '',
    intent_kind: approval.intent_kind || '',
    step_id: approval.step_id || '',
    planner_step_id: approval.planner_step_id || '',
    capability_id: approval.capability_id || '',
    replan_request_id: approval.replan_request_id || '',
    replan_trigger: approval.replan_trigger || '',
    replan_triggers: approval.replan_triggers || [],
    replan_signal_ids: approval.replan_signal_ids || [],
    runtime_doctrine: approval.runtime_doctrine || '',
    runtime_stage: approval.runtime_stage || '',
    runtime_role: approval.runtime_role || '',
    requires_observation: approval.requires_observation || false,
    requires_post_action_verification: approval.requires_post_action_verification || false,
    task_workspace_items: approval.task_workspace_items || [],
    task_verification_targets: approval.task_verification_targets || [],
    requested_at: approval.requested_at || '',
    resolved_at: approval.resolved_at || '',
    risk_level: approval.risk_level || '',
    run_id: approval.run_id || '',
    status: approval.status || '',
    tool: approval.tool_name || legacyTool,
  };
}

export function publicArtifactsOrLegacy(
  publicArtifacts: ArtifactSnapshot[] | undefined,
  legacyArtifacts: Array<Record<string, unknown>> | undefined,
): Array<Record<string, unknown>> {
  if (publicArtifacts?.length) {
    return publicArtifacts.map((artifact) => ({
      artifact_id: artifact.artifact_id,
      artifact_kind: artifact.kind,
      capability_id: artifact.capability_id || '',
      created_at: artifact.created_at,
      decision_id: artifact.decision_id || '',
      kind: artifact.kind,
      intent_kind: artifact.intent_kind || '',
      mime_type: artifact.mime_type,
      path: artifact.path || '',
      plan_id: artifact.plan_id || '',
      planner_step_id: artifact.planner_step_id || '',
      planning_reason: artifact.planning_reason || '',
      preview_text: artifact.preview_text,
      replan_request_id: artifact.replan_request_id || '',
      replan_signal_ids: artifact.replan_signal_ids || [],
      replan_trigger: artifact.replan_trigger || '',
      replan_triggers: artifact.replan_triggers || [],
      requires_observation: artifact.requires_observation || false,
      requires_post_action_verification: artifact.requires_post_action_verification || false,
      run_id: artifact.run_id || artifact.source_run_id || '',
      runtime_doctrine: artifact.runtime_doctrine || '',
      runtime_role: artifact.runtime_role || '',
      runtime_stage: artifact.runtime_stage || '',
      size_bytes: artifact.size_bytes,
      source: artifact.source || '',
      group_id: artifact.group_id || '',
      group_run_id: artifact.group_run_id || '',
      source_runnable_id: artifact.source_runnable_id || '',
      source_runnable_name: artifact.source_runnable_name || '',
      source_run_id: artifact.source_run_id || artifact.run_id || '',
      source_tool: artifact.source_tool || '',
      step_id: artifact.step_id || '',
      title: artifact.title,
      tool_plan_id: artifact.tool_plan_id || '',
      url: artifact.url,
      workflow_id: artifact.workflow_id || '',
      workflow_run_id: artifact.workflow_run_id || '',
      workflow_node_id: artifact.workflow_node_id || '',
      workflow_node_label: artifact.workflow_node_label || '',
      workflow_step_label: artifact.workflow_node_label || '',
    }));
  }
  return legacyArtifacts || [];
}
