import type { ApprovalCardSnapshot, PublicRunEvent, ToolCallSnapshot } from './types';
import {
  runtimeEventIsDailyDesktopToolEvent,
  runtimeEventIsDesktopIntent,
  runtimeEventIsDesktopPermissionRecovery,
} from './desktopEvents';
import { publicRunEventIsSecret } from './runEvents';

type ApprovalReplayCorrelationKeys = {
  strongKeys: string[];
  weakKey: string;
};

type ApprovalReplayWeakIndex = number | 'ambiguous';

const TOOL_INPUT_RESOLUTION_EVENT_TYPE = 'agent.tool.input_resolved';
const PLANNER_TRACE_KEYS = [
  'source',
  'planning_reason',
  'decision_id',
  'plan_id',
  'tool_plan_id',
  'intent_kind',
  'step_id',
  'planner_step_id',
  'capability_id',
  'capability_title',
  'capability_status',
  'capability_reason',
  'replan_request_id',
  'replan_trigger',
];
const RUNTIME_TRACE_KEYS = [
  'capability_selected_tools',
  'capability_planned_step_ids',
  'replan_triggers',
  'replan_signal_ids',
  'runtime_doctrine',
  'runtime_stage',
  'runtime_role',
  'requires_observation',
  'requires_post_action_verification',
  'deferred_tool',
  'deferred_input',
  'deferred_context',
  'deferred_continuation',
];
const TASK_CONTEXT_KEYS = [
  'core_id',
  'workspace_id',
  'task_id',
];
const TRACE_KEYS = [
  ...TASK_CONTEXT_KEYS,
  ...PLANNER_TRACE_KEYS,
  ...RUNTIME_TRACE_KEYS,
];

export function toolCallsFromRunEventReplay(events: PublicRunEvent[]): ToolCallSnapshot[] {
  const calls: ToolCallSnapshot[] = [];
  const activeByKey = new Map<string, number>();
  events.forEach((event) => {
    if (publicRunEventIsSecret(event)) return;
    const toolCall = toolCallFromRunEvent(event);
    if (!toolCall) return;
    const key = toolCallCorrelationKey(event, toolCall);
    const activeIndex = key ? activeByKey.get(key) : undefined;
    const mergeIndex = activeIndex === undefined && runtimeEventIsDailyDesktopToolEvent(event.event_type)
      ? latestMatchingToolCallIndex(calls, toolCall)
      : activeIndex;
    if (mergeIndex === undefined) {
      const nextIndex = calls.length;
      calls.push(toolCall);
      if (key && !toolCallStatusIsTerminal(toolCall.status)) activeByKey.set(key, nextIndex);
      return;
    }
    calls[mergeIndex] = mergeToolCallReplayTrace(calls[mergeIndex], toolCall);
    if (key) {
      if (toolCallStatusIsTerminal(toolCall.status)) activeByKey.delete(key);
      else activeByKey.set(key, mergeIndex);
    }
  });
  return calls;
}

export function mergeToolCallSnapshots(
  timelineToolCalls: ToolCallSnapshot[],
  replayToolCalls: ToolCallSnapshot[],
): ToolCallSnapshot[] {
  const calls: ToolCallSnapshot[] = [];
  const byId = new Map<string, number>();
  const byMatchKey = new Map<string, number>();
  function indexToolCall(toolCall: ToolCallSnapshot, index: number) {
    if (toolCall.tool_call_id) byId.set(toolCall.tool_call_id, index);
    byMatchKey.set(toolCallSnapshotMatchKey(toolCall), index);
  }

  timelineToolCalls.forEach((toolCall) => {
    const index = calls.length;
    calls.push(toolCall);
    indexToolCall(toolCall, index);
  });
  replayToolCalls.forEach((toolCall) => {
    const matchKey = toolCallSnapshotMatchKey(toolCall);
    const existingIndex = byId.get(toolCall.tool_call_id) ?? byMatchKey.get(matchKey);
    if (existingIndex === undefined) {
      const index = calls.length;
      calls.push(toolCall);
      indexToolCall(toolCall, index);
      return;
    }
    calls[existingIndex] = mergeToolCallTrace(calls[existingIndex], toolCall);
    indexToolCall(calls[existingIndex], existingIndex);
  });
  return calls;
}

export function artifactsFromRunEventReplay(events: PublicRunEvent[]): Array<Record<string, unknown>> {
  return events
    .filter((event) => !publicRunEventIsSecret(event))
    .map(artifactFromRunEvent)
    .filter((artifact): artifact is Record<string, unknown> => Boolean(artifact));
}

export function mergeArtifactSnapshots(
  timelineArtifacts: Array<Record<string, unknown>>,
  replayArtifacts: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const byKey = new Map<string, Record<string, unknown>>();
  timelineArtifacts.forEach((artifact, index) => {
    byKey.set(artifactRecordKey(artifact, index), artifact);
  });
  replayArtifacts.forEach((artifact, index) => {
    const key = artifactRecordKey(artifact, index);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, artifact);
      return;
    }
    byKey.set(key, mergeArtifactTrace(existing, artifact));
  });
  return Array.from(byKey.values());
}

export function approvalsFromRunEventReplay(events: PublicRunEvent[]): ApprovalCardSnapshot[] {
  const approvals: ApprovalCardSnapshot[] = [];
  const activeByStrongKey = new Map<string, number>();
  const activeByWeakKey = new Map<string, ApprovalReplayWeakIndex>();
  const activeKeysByIndex = new Map<number, ApprovalReplayCorrelationKeys>();
  events.forEach((event) => {
    if (publicRunEventIsSecret(event)) return;
    const approval = approvalFromRunEvent(event);
    if (!approval) return;
    const keys = approvalReplayCorrelationKeys(approval);
    const activeIndex = approvalReplayActiveIndex(
      keys,
      activeByStrongKey,
      activeByWeakKey,
      approval.status !== 'pending',
    );
    if (activeIndex === undefined) {
      const nextIndex = approvals.length;
      approvals.push(approval);
      if (approval.status === 'pending') {
        registerActiveApprovalReplay(
          nextIndex,
          keys,
          activeByStrongKey,
          activeByWeakKey,
          activeKeysByIndex,
        );
      }
      return;
    }
    approvals[activeIndex] = mergeApprovalReplayTrace(approvals[activeIndex], approval);
    if (approval.status === 'pending') {
      registerActiveApprovalReplay(
        activeIndex,
        keys,
        activeByStrongKey,
        activeByWeakKey,
        activeKeysByIndex,
      );
    } else {
      unregisterActiveApprovalReplay(
        activeIndex,
        activeByStrongKey,
        activeByWeakKey,
        activeKeysByIndex,
      );
    }
  });
  return approvals;
}

export function mergeApprovalSnapshots(
  timelineApprovals: ApprovalCardSnapshot[],
  replayApprovals: ApprovalCardSnapshot[],
): ApprovalCardSnapshot[] {
  const byKey = new Map<string, ApprovalCardSnapshot>();
  timelineApprovals.forEach((approval, index) => {
    byKey.set(approvalRecordKey(approval, index), approval);
  });
  replayApprovals.forEach((approval, index) => {
    const key = approvalRecordKey(approval, index);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, approval);
      return;
    }
    byKey.set(key, mergeApprovalTrace(existing, approval));
  });
  return Array.from(byKey.values());
}

function approvalFromRunEvent(event: PublicRunEvent): ApprovalCardSnapshot | null {
  if (!isApprovalRunEvent(event.event_type)) return null;
  const payload = publicRunEventPayloadWithContext(event);
  const source = objectPreview(payload.pending_approval)
    || objectPreview(payload.approval)
    || payload;
  const toolName = publicRunEventPayloadString(source, 'tool_name')
    || publicRunEventPayloadString(source, 'tool')
    || approvalToolFromRunEvent(event.event_type)
    || event.detail
    || 'approval';
  const approvalId = publicRunEventPayloadString(source, 'approval_id')
    || `${event.run_id}:${event.event_type}:${event.sequence}`;
  const status = publicRunEventPayloadString(source, 'status') || approvalStatusFromRunEvent(event.event_type);
  const inputPreview = objectPreview(source.input_preview) || objectPreview(source.input) || {};
  return {
    approval_id: approvalId,
    description: publicRunEventPayloadString(source, 'description') || null,
    input_preview: inputPreview,
    policy_reason: publicRunEventPayloadString(source, 'policy_reason') || null,
    requested_at: publicRunEventPayloadString(source, 'requested_at') || event.created_at || '',
    resolved_at: publicRunEventPayloadString(source, 'resolved_at')
      || (status !== 'pending' ? event.created_at || '' : null),
    risk_level: publicRunEventPayloadString(source, 'risk_level')
      || publicRunEventPayloadString(source, 'risk')
      || null,
    run_id: publicRunEventPayloadString(source, 'run_id') || event.run_id,
    source_run_id: publicRunEventPayloadString(source, 'source_run_id')
      || publicRunEventPayloadString(payload, 'source_run_id')
      || null,
    source_runnable_id: publicRunEventPayloadString(source, 'source_runnable_id')
      || publicRunEventPayloadString(source, 'source_agent_id')
      || publicRunEventPayloadString(source, 'member_agent_id')
      || publicRunEventPayloadString(source, 'agent_id')
      || publicRunEventPayloadString(payload, 'source_runnable_id')
      || publicRunEventPayloadString(payload, 'source_agent_id')
      || publicRunEventPayloadString(payload, 'member_agent_id')
      || publicRunEventPayloadString(payload, 'agent_id')
      || null,
    source_runnable_name: publicRunEventPayloadString(source, 'source_runnable_name')
      || publicRunEventPayloadString(source, 'source_agent_name')
      || publicRunEventPayloadString(source, 'member_agent_name')
      || publicRunEventPayloadString(source, 'agent_name')
      || publicRunEventPayloadString(payload, 'source_runnable_name')
      || publicRunEventPayloadString(payload, 'source_agent_name')
      || publicRunEventPayloadString(payload, 'member_agent_name')
      || publicRunEventPayloadString(payload, 'agent_name')
      || null,
    workflow_id: publicRunEventPayloadString(source, 'workflow_id')
      || publicRunEventPayloadString(payload, 'workflow_id')
      || null,
    workflow_run_id: publicRunEventPayloadString(source, 'workflow_run_id')
      || publicRunEventPayloadString(payload, 'workflow_run_id')
      || null,
    workflow_node_id: publicRunEventPayloadString(source, 'workflow_node_id')
      || publicRunEventPayloadString(payload, 'workflow_node_id')
      || null,
    workflow_node_label: publicRunEventPayloadString(source, 'workflow_node_label')
      || publicRunEventPayloadString(payload, 'workflow_node_label')
      || null,
    group_id: publicRunEventPayloadString(source, 'group_id')
      || publicRunEventPayloadString(payload, 'group_id')
      || null,
    group_run_id: publicRunEventPayloadString(source, 'group_run_id')
      || publicRunEventPayloadString(source, 'run_group_id')
      || publicRunEventPayloadString(payload, 'group_run_id')
      || publicRunEventPayloadString(payload, 'run_group_id')
      || null,
    core_id: eventTraceString(source, payload, inputPreview, 'core_id'),
    workspace_id: eventTraceString(source, payload, inputPreview, 'workspace_id'),
    task_id: eventTraceString(source, payload, inputPreview, 'task_id'),
    source: eventTraceString(source, payload, inputPreview, 'source'),
    planning_reason: eventTraceString(source, payload, inputPreview, 'planning_reason'),
    decision_id: eventTraceString(source, payload, inputPreview, 'decision_id'),
    plan_id: eventTraceString(source, payload, inputPreview, 'plan_id'),
    tool_plan_id: eventTraceString(source, payload, inputPreview, 'tool_plan_id'),
    intent_kind: eventTraceString(source, payload, inputPreview, 'intent_kind'),
    step_id: eventTraceString(source, payload, inputPreview, 'step_id'),
    planner_step_id: eventTraceString(source, payload, inputPreview, 'planner_step_id'),
    capability_id: eventTraceString(source, payload, inputPreview, 'capability_id'),
    replan_request_id: eventTraceString(source, payload, inputPreview, 'replan_request_id'),
    replan_trigger: eventTraceString(source, payload, inputPreview, 'replan_trigger'),
    replan_triggers: eventTraceStringList(source, payload, inputPreview, 'replan_triggers'),
    replan_signal_ids: eventTraceStringList(source, payload, inputPreview, 'replan_signal_ids'),
    runtime_doctrine: eventTraceString(source, payload, inputPreview, 'runtime_doctrine'),
    runtime_stage: eventTraceString(source, payload, inputPreview, 'runtime_stage'),
    runtime_role: eventTraceString(source, payload, inputPreview, 'runtime_role'),
    requires_observation: eventTraceBool(source, payload, inputPreview, 'requires_observation'),
    requires_post_action_verification: eventTraceBool(source, payload, inputPreview, 'requires_post_action_verification'),
    deferred_tool: eventTraceString(source, payload, inputPreview, 'deferred_tool'),
    deferred_input: objectPreview(source.deferred_input)
      || objectPreview(payload.deferred_input)
      || objectPreview(inputPreview.deferred_input)
      || {},
    deferred_context: objectPreview(source.deferred_context)
      || objectPreview(payload.deferred_context)
      || objectPreview(inputPreview.deferred_context)
      || {},
    deferred_continuation: mergeRecordLists(
      recordList(source.deferred_continuation),
      recordList(payload.deferred_continuation),
      recordList(inputPreview.deferred_continuation),
    ),
    task_workspace_items: approvalTaskWorkspaceItems(source, payload, inputPreview),
    task_verification_targets: approvalTaskVerificationTargets(source, payload, inputPreview),
    status,
    title: publicRunEventPayloadString(source, 'title') || `Approval · ${toolName}`,
    tool_name: toolName,
  };
}

function toolCallFromRunEvent(event: PublicRunEvent): ToolCallSnapshot | null {
  if (!isToolRunEvent(event.event_type)) return null;
  const payload = publicRunEventPayloadWithContext(event);
  const approval = objectPreview(payload.pending_approval)
    || objectPreview(payload.approval)
    || {};
  const approvalId = publicRunEventPayloadString(payload, 'approval_id')
    || publicRunEventPayloadString(approval, 'approval_id')
    || publicRunEventPayloadString(approval, 'id');
  const riskLevel = publicRunEventPayloadString(payload, 'risk_level')
    || publicRunEventPayloadString(payload, 'risk')
    || publicRunEventPayloadString(approval, 'risk_level')
    || publicRunEventPayloadString(approval, 'risk');
  const policyReason = publicRunEventPayloadString(payload, 'policy_reason')
    || publicRunEventPayloadString(approval, 'policy_reason')
    || publicRunEventPayloadString(approval, 'reason');
  const outputPreview = toolCallOutputPreviewFromPayload(event.event_type, payload);
  const status = toolStatusFromRunEventPayload(event.event_type, payload, outputPreview);
  const toolName = publicRunEventPayloadString(payload, 'tool_name')
    || publicRunEventPayloadString(payload, 'tool')
    || event.detail
    || 'tool';
  const baseInputPreview = objectPreview(payload.input_preview)
    || objectPreview(payload.input)
    || objectPreview(payload.arguments)
    || objectPreview(payload.args)
    || {};
  const inputPreview = toolCallInputPreviewWithTraceContext(
    event.event_type === TOOL_INPUT_RESOLUTION_EVENT_TYPE
      ? toolInputResolutionPreview(payload, baseInputPreview)
      : baseInputPreview,
    {
      approval_id: approvalId,
      risk_level: riskLevel,
      policy_reason: policyReason,
      group_id: payload.group_id,
      group_run_id: payload.group_run_id || payload.run_group_id,
      member_agent_id: payload.member_agent_id,
      member_agent_name: payload.member_agent_name,
      workflow_id: payload.workflow_id,
      workflow_run_id: payload.workflow_run_id,
      workflow_node_id: payload.workflow_node_id,
      workflow_node_label: payload.workflow_node_label,
      ...Object.fromEntries(TRACE_KEYS.map((key) => [key, payload[key]])),
    },
  );
  return {
    tool_call_id: publicRunEventPayloadString(payload, 'tool_call_id')
      || publicRunEventPayloadString(payload, 'id')
      || event.event_id
      || `${event.run_id}:${event.event_type}:${event.sequence}`,
    run_id: event.run_id,
    source_run_id: publicRunEventPayloadString(payload, 'source_run_id') || null,
    source_runnable_id: publicRunEventPayloadString(payload, 'source_runnable_id')
      || publicRunEventPayloadString(payload, 'source_agent_id')
      || publicRunEventPayloadString(payload, 'member_agent_id')
      || publicRunEventPayloadString(payload, 'agent_id')
      || null,
    source_runnable_name: publicRunEventPayloadString(payload, 'source_runnable_name')
      || publicRunEventPayloadString(payload, 'source_agent_name')
      || publicRunEventPayloadString(payload, 'member_agent_name')
      || publicRunEventPayloadString(payload, 'agent_name')
      || null,
    workflow_id: publicRunEventPayloadString(payload, 'workflow_id') || null,
    workflow_run_id: publicRunEventPayloadString(payload, 'workflow_run_id') || null,
    workflow_node_id: publicRunEventPayloadString(payload, 'workflow_node_id') || null,
    workflow_node_label: publicRunEventPayloadString(payload, 'workflow_node_label') || null,
    group_id: publicRunEventPayloadString(payload, 'group_id') || null,
    group_run_id: publicRunEventPayloadString(payload, 'group_run_id')
      || publicRunEventPayloadString(payload, 'run_group_id')
      || null,
    core_id: plannerTraceString(payload, inputPreview, 'core_id'),
    workspace_id: plannerTraceString(payload, inputPreview, 'workspace_id'),
    task_id: plannerTraceString(payload, inputPreview, 'task_id'),
    source: plannerTraceString(payload, inputPreview, 'source'),
    planning_reason: plannerTraceString(payload, inputPreview, 'planning_reason'),
    decision_id: plannerTraceString(payload, inputPreview, 'decision_id'),
    plan_id: plannerTraceString(payload, inputPreview, 'plan_id'),
    tool_plan_id: plannerTraceString(payload, inputPreview, 'tool_plan_id'),
    intent_kind: plannerTraceString(payload, inputPreview, 'intent_kind'),
    step_id: plannerTraceString(payload, inputPreview, 'step_id'),
    planner_step_id: plannerTraceString(payload, inputPreview, 'planner_step_id'),
    capability_id: plannerTraceString(payload, inputPreview, 'capability_id'),
    capability_title: plannerTraceString(payload, inputPreview, 'capability_title'),
    capability_status: plannerTraceString(payload, inputPreview, 'capability_status'),
    capability_reason: plannerTraceString(payload, inputPreview, 'capability_reason'),
    capability_selected_tools: plannerTraceStringList(payload, inputPreview, 'capability_selected_tools'),
    capability_planned_step_ids: plannerTraceStringList(payload, inputPreview, 'capability_planned_step_ids'),
    replan_request_id: plannerTraceString(payload, inputPreview, 'replan_request_id'),
    replan_trigger: plannerTraceString(payload, inputPreview, 'replan_trigger'),
    replan_triggers: plannerTraceStringList(payload, inputPreview, 'replan_triggers'),
    replan_signal_ids: plannerTraceStringList(payload, inputPreview, 'replan_signal_ids'),
    runtime_doctrine: plannerTraceString(payload, inputPreview, 'runtime_doctrine'),
    runtime_stage: plannerTraceString(payload, inputPreview, 'runtime_stage'),
    runtime_role: plannerTraceString(payload, inputPreview, 'runtime_role'),
    requires_observation: plannerTraceBool(payload, inputPreview, 'requires_observation'),
    requires_post_action_verification: plannerTraceBool(payload, inputPreview, 'requires_post_action_verification'),
    deferred_tool: plannerTraceString(payload, inputPreview, 'deferred_tool'),
    deferred_input: objectPreview(payload.deferred_input) || objectPreview(inputPreview.deferred_input) || {},
    deferred_context: objectPreview(payload.deferred_context) || objectPreview(inputPreview.deferred_context) || {},
    deferred_continuation: mergeRecordLists(
      recordList(payload.deferred_continuation),
      recordList(inputPreview.deferred_continuation),
    ),
    task_workspace_items: toolCallTaskWorkspaceItems(payload, inputPreview),
    task_verification_targets: toolCallTaskVerificationTargets(payload, inputPreview),
    tool_name: toolName,
    status,
    risk_level: riskLevel || null,
    policy_reason: policyReason || null,
    input_preview: inputPreview,
    output_preview: outputPreview,
    metadata: toolCallMetadata(payload),
    approval_id: approvalId || null,
    started_at: publicRunEventPayloadString(payload, 'started_at') || event.created_at || '',
    completed_at: publicRunEventPayloadString(payload, 'completed_at')
      || (toolCallStatusIsTerminal(status) ? event.created_at || null : null),
  };
}

function artifactFromRunEvent(event: PublicRunEvent): Record<string, unknown> | null {
  if (!isArtifactRunEvent(event.event_type)) return null;
  const payload = publicRunEventPayloadWithContext(event);
  let artifactPayload: Record<string, unknown> | null = null;
  if (event.event_type === 'artifact.created' || event.event_type === 'agent.artifact.write') {
    artifactPayload = { ...(objectPreview(payload.artifact) || payload) };
    if (event.event_type === 'agent.artifact.write') {
      artifactPayload.kind = artifactPayload.kind || 'agent_artifact';
      artifactPayload.path = artifactPayload.path || event.detail;
    } else if (payload.workflow_node_id || payload.workflow_node_label) {
      artifactPayload.kind = artifactPayload.kind || payload.kind || 'workflow_artifact';
      artifactPayload.title = artifactPayload.title
        || payload.title
        || payload.workflow_node_label
        || artifactPayload.path
        || artifactPayload.artifact_path
        || 'Workflow Artifact';
      artifactPayload.workflow_id = artifactPayload.workflow_id || payload.workflow_id;
      artifactPayload.workflow_run_id = artifactPayload.workflow_run_id || payload.workflow_run_id || event.run_id;
      artifactPayload.workflow_node_id = artifactPayload.workflow_node_id || payload.workflow_node_id;
      artifactPayload.workflow_node_label = artifactPayload.workflow_node_label || payload.workflow_node_label;
      artifactPayload.workflow_step_label = artifactPayload.workflow_step_label || payload.workflow_node_label;
    } else if (payload.group_id || payload.group_run_id || payload.run_group_id) {
      artifactPayload.kind = artifactPayload.kind || 'group_artifact';
      artifactPayload.group_id = artifactPayload.group_id || payload.group_id;
      artifactPayload.group_run_id = artifactPayload.group_run_id || payload.group_run_id || payload.run_group_id || event.run_id;
      artifactPayload.source_runnable_name = artifactPayload.source_runnable_name || payload.member_agent_name;
      artifactPayload.source_runnable_id = artifactPayload.source_runnable_id || payload.member_agent_id;
      if (payload.member_agent_name && !artifactPayload.title) {
        artifactPayload.title = `${payload.member_agent_name} / ${artifactPayload.path || artifactPayload.artifact_path || 'Artifact'}`;
      }
    }
  } else if (event.event_type === 'group.artifact.created' || event.event_type === 'group.shared_artifact.created') {
    artifactPayload = { ...(objectPreview(payload.artifact) || payload) };
    artifactPayload.kind = artifactPayload.kind || 'group_artifact';
    artifactPayload.source_runnable_name = artifactPayload.source_runnable_name || payload.member_agent_name;
    artifactPayload.source_runnable_id = artifactPayload.source_runnable_id || payload.member_agent_id;
    artifactPayload.group_id = artifactPayload.group_id || payload.group_id;
    artifactPayload.group_run_id = artifactPayload.group_run_id || payload.group_run_id || payload.run_group_id;
  } else if (event.event_type === 'workflow.node.artifact') {
    artifactPayload = {
      kind: 'workflow_artifact',
      title: payload.workflow_node_label || 'Workflow Artifact',
      workflow_id: payload.workflow_id,
      workflow_run_id: payload.workflow_run_id || event.run_id,
      workflow_node_id: payload.workflow_node_id,
      workflow_node_label: payload.workflow_node_label,
      workflow_step_label: payload.workflow_node_label,
      ...(objectPreview(payload.artifact) || payload),
    };
  }
  if (!artifactPayload) return null;
  mergeArtifactTraceContext(artifactPayload, payload);
  const path = publicRunEventPayloadString(artifactPayload, 'path')
    || publicRunEventPayloadString(artifactPayload, 'artifact_path');
  const artifactId = publicRunEventPayloadString(artifactPayload, 'artifact_id')
    || publicRunEventPayloadString(artifactPayload, 'id');
  if (!artifactId && !path) return null;
  return {
    ...artifactPayload,
    artifact_id: artifactId || `${event.run_id}:${path || event.event_type}:${event.sequence}`,
    created_at: publicRunEventPayloadString(artifactPayload, 'created_at') || event.created_at || '',
    kind: publicRunEventPayloadString(artifactPayload, 'kind') || 'artifact',
    path,
    run_id: publicRunEventPayloadString(artifactPayload, 'run_id') || event.run_id,
    source_run_id: publicRunEventPayloadString(artifactPayload, 'source_run_id') || event.run_id,
    source_tool: publicRunEventPayloadString(artifactPayload, 'source_tool')
      || publicRunEventPayloadString(artifactPayload, 'tool')
      || null,
    source_runnable_id: publicRunEventPayloadString(artifactPayload, 'source_runnable_id') || null,
    source_runnable_name: publicRunEventPayloadString(artifactPayload, 'source_runnable_name') || null,
    workflow_id: publicRunEventPayloadString(artifactPayload, 'workflow_id') || null,
    workflow_run_id: publicRunEventPayloadString(artifactPayload, 'workflow_run_id') || null,
    workflow_node_id: publicRunEventPayloadString(artifactPayload, 'workflow_node_id') || null,
    workflow_node_label: publicRunEventPayloadString(artifactPayload, 'workflow_node_label') || null,
    group_id: publicRunEventPayloadString(artifactPayload, 'group_id') || null,
    group_run_id: publicRunEventPayloadString(artifactPayload, 'group_run_id')
      || publicRunEventPayloadString(artifactPayload, 'run_group_id')
      || null,
    title: publicRunEventPayloadString(artifactPayload, 'title') || path || 'Artifact',
  };
}

function mergeApprovalTrace(current: ApprovalCardSnapshot, incoming: ApprovalCardSnapshot): ApprovalCardSnapshot {
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
    core_id: current.core_id || incoming.core_id || null,
    workspace_id: current.workspace_id || incoming.workspace_id || null,
    task_id: current.task_id || incoming.task_id || null,
    source: current.source || incoming.source || null,
    planning_reason: current.planning_reason || incoming.planning_reason || null,
    decision_id: current.decision_id || incoming.decision_id || null,
    plan_id: current.plan_id || incoming.plan_id || null,
    tool_plan_id: current.tool_plan_id || incoming.tool_plan_id || null,
    intent_kind: current.intent_kind || incoming.intent_kind || null,
    step_id: current.step_id || incoming.step_id || null,
    planner_step_id: current.planner_step_id || incoming.planner_step_id || null,
    capability_id: current.capability_id || incoming.capability_id || null,
    capability_title: current.capability_title || incoming.capability_title || null,
    capability_status: current.capability_status || incoming.capability_status || null,
    capability_reason: current.capability_reason || incoming.capability_reason || null,
    capability_selected_tools: mergeTraceStringLists(
      current.capability_selected_tools,
      incoming.capability_selected_tools,
    ),
    capability_planned_step_ids: mergeTraceStringLists(
      current.capability_planned_step_ids,
      incoming.capability_planned_step_ids,
    ),
    replan_request_id: current.replan_request_id || incoming.replan_request_id || null,
    replan_trigger: current.replan_trigger || incoming.replan_trigger || null,
    replan_triggers: mergeTraceStringLists(current.replan_triggers, incoming.replan_triggers),
    replan_signal_ids: mergeTraceStringLists(current.replan_signal_ids, incoming.replan_signal_ids),
    runtime_doctrine: current.runtime_doctrine || incoming.runtime_doctrine || null,
    runtime_stage: current.runtime_stage || incoming.runtime_stage || null,
    runtime_role: current.runtime_role || incoming.runtime_role || null,
    requires_observation: current.requires_observation || incoming.requires_observation || null,
    requires_post_action_verification: current.requires_post_action_verification
      || incoming.requires_post_action_verification
      || null,
    deferred_tool: current.deferred_tool || incoming.deferred_tool || null,
    deferred_input: {
      ...(incoming.deferred_input || {}),
      ...(current.deferred_input || {}),
    },
    deferred_context: {
      ...(incoming.deferred_context || {}),
      ...(current.deferred_context || {}),
    },
    deferred_continuation: mergeRecordLists(
      current.deferred_continuation,
      incoming.deferred_continuation,
    ),
    task_workspace_items: mergeRecordLists(current.task_workspace_items, incoming.task_workspace_items),
    task_verification_targets: mergeRecordLists(
      current.task_verification_targets,
      incoming.task_verification_targets,
    ),
  };
}

function mergeApprovalReplayTrace(
  current: ApprovalCardSnapshot,
  incoming: ApprovalCardSnapshot,
): ApprovalCardSnapshot {
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
    core_id: current.core_id || incoming.core_id || null,
    workspace_id: current.workspace_id || incoming.workspace_id || null,
    task_id: current.task_id || incoming.task_id || null,
    source: current.source || incoming.source || null,
    planning_reason: current.planning_reason || incoming.planning_reason || null,
    decision_id: current.decision_id || incoming.decision_id || null,
    plan_id: current.plan_id || incoming.plan_id || null,
    tool_plan_id: current.tool_plan_id || incoming.tool_plan_id || null,
    intent_kind: current.intent_kind || incoming.intent_kind || null,
    step_id: current.step_id || incoming.step_id || null,
    planner_step_id: current.planner_step_id || incoming.planner_step_id || null,
    capability_id: current.capability_id || incoming.capability_id || null,
    capability_title: current.capability_title || incoming.capability_title || null,
    capability_status: current.capability_status || incoming.capability_status || null,
    capability_reason: current.capability_reason || incoming.capability_reason || null,
    capability_selected_tools: mergeTraceStringLists(
      current.capability_selected_tools,
      incoming.capability_selected_tools,
    ),
    capability_planned_step_ids: mergeTraceStringLists(
      current.capability_planned_step_ids,
      incoming.capability_planned_step_ids,
    ),
    replan_request_id: current.replan_request_id || incoming.replan_request_id || null,
    replan_trigger: current.replan_trigger || incoming.replan_trigger || null,
    replan_triggers: mergeTraceStringLists(current.replan_triggers, incoming.replan_triggers),
    replan_signal_ids: mergeTraceStringLists(current.replan_signal_ids, incoming.replan_signal_ids),
    runtime_doctrine: current.runtime_doctrine || incoming.runtime_doctrine || null,
    runtime_stage: current.runtime_stage || incoming.runtime_stage || null,
    runtime_role: current.runtime_role || incoming.runtime_role || null,
    requires_observation: current.requires_observation || incoming.requires_observation || null,
    requires_post_action_verification: current.requires_post_action_verification
      || incoming.requires_post_action_verification
      || null,
    deferred_tool: current.deferred_tool || incoming.deferred_tool || null,
    deferred_input: {
      ...(incoming.deferred_input || {}),
      ...(current.deferred_input || {}),
    },
    deferred_context: {
      ...(incoming.deferred_context || {}),
      ...(current.deferred_context || {}),
    },
    deferred_continuation: mergeRecordLists(
      current.deferred_continuation,
      incoming.deferred_continuation,
    ),
    task_workspace_items: mergeRecordLists(current.task_workspace_items, incoming.task_workspace_items),
    task_verification_targets: mergeRecordLists(
      current.task_verification_targets,
      incoming.task_verification_targets,
    ),
    description: incoming.description || current.description || null,
    input_preview: {
      ...(current.input_preview || {}),
      ...(incoming.input_preview || {}),
    },
    policy_reason: current.policy_reason || incoming.policy_reason || null,
    requested_at: current.requested_at || incoming.requested_at || '',
    resolved_at: incoming.resolved_at || current.resolved_at || null,
    risk_level: current.risk_level || incoming.risk_level || null,
    status: incoming.status || current.status,
    tool_name: current.tool_name || incoming.tool_name,
  };
}

function mergeToolCallTrace(current: ToolCallSnapshot, incoming: ToolCallSnapshot): ToolCallSnapshot {
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
    core_id: current.core_id || incoming.core_id || null,
    workspace_id: current.workspace_id || incoming.workspace_id || null,
    task_id: current.task_id || incoming.task_id || null,
    source: current.source || incoming.source || null,
    planning_reason: current.planning_reason || incoming.planning_reason || null,
    decision_id: current.decision_id || incoming.decision_id || null,
    plan_id: current.plan_id || incoming.plan_id || null,
    tool_plan_id: current.tool_plan_id || incoming.tool_plan_id || null,
    intent_kind: current.intent_kind || incoming.intent_kind || null,
    step_id: current.step_id || incoming.step_id || null,
    planner_step_id: current.planner_step_id || incoming.planner_step_id || null,
    capability_id: current.capability_id || incoming.capability_id || null,
    capability_title: current.capability_title || incoming.capability_title || null,
    capability_status: current.capability_status || incoming.capability_status || null,
    capability_reason: current.capability_reason || incoming.capability_reason || null,
    capability_selected_tools: mergeTraceStringLists(
      current.capability_selected_tools,
      incoming.capability_selected_tools,
    ),
    capability_planned_step_ids: mergeTraceStringLists(
      current.capability_planned_step_ids,
      incoming.capability_planned_step_ids,
    ),
    replan_request_id: current.replan_request_id || incoming.replan_request_id || null,
    replan_trigger: current.replan_trigger || incoming.replan_trigger || null,
    replan_triggers: mergeTraceStringLists(current.replan_triggers, incoming.replan_triggers),
    replan_signal_ids: mergeTraceStringLists(current.replan_signal_ids, incoming.replan_signal_ids),
    runtime_doctrine: current.runtime_doctrine || incoming.runtime_doctrine || null,
    runtime_stage: current.runtime_stage || incoming.runtime_stage || null,
    runtime_role: current.runtime_role || incoming.runtime_role || null,
    requires_observation: current.requires_observation ?? incoming.requires_observation ?? null,
    requires_post_action_verification: current.requires_post_action_verification ?? incoming.requires_post_action_verification ?? null,
    deferred_tool: current.deferred_tool || incoming.deferred_tool || null,
    deferred_input: {
      ...(incoming.deferred_input || {}),
      ...(current.deferred_input || {}),
    },
    deferred_context: {
      ...(incoming.deferred_context || {}),
      ...(current.deferred_context || {}),
    },
    deferred_continuation: mergeRecordLists(
      current.deferred_continuation,
      incoming.deferred_continuation,
    ),
    task_workspace_items: mergeRecordLists(current.task_workspace_items, incoming.task_workspace_items),
    task_verification_targets: mergeRecordLists(
      current.task_verification_targets,
      incoming.task_verification_targets,
    ),
    policy_reason: current.policy_reason || incoming.policy_reason || null,
    metadata: {
      ...(incoming.metadata || {}),
      ...(current.metadata || {}),
    },
  };
}

function mergeToolCallReplayTrace(current: ToolCallSnapshot, incoming: ToolCallSnapshot): ToolCallSnapshot {
  const outputPreview = {
    ...(current.output_preview || {}),
    ...(incoming.output_preview || {}),
  };
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
    core_id: current.core_id || incoming.core_id || null,
    workspace_id: current.workspace_id || incoming.workspace_id || null,
    task_id: current.task_id || incoming.task_id || null,
    source: current.source || incoming.source || null,
    planning_reason: current.planning_reason || incoming.planning_reason || null,
    decision_id: current.decision_id || incoming.decision_id || null,
    plan_id: current.plan_id || incoming.plan_id || null,
    tool_plan_id: current.tool_plan_id || incoming.tool_plan_id || null,
    intent_kind: current.intent_kind || incoming.intent_kind || null,
    step_id: current.step_id || incoming.step_id || null,
    planner_step_id: current.planner_step_id || incoming.planner_step_id || null,
    capability_id: current.capability_id || incoming.capability_id || null,
    capability_title: current.capability_title || incoming.capability_title || null,
    capability_status: current.capability_status || incoming.capability_status || null,
    capability_reason: current.capability_reason || incoming.capability_reason || null,
    capability_selected_tools: mergeTraceStringLists(
      current.capability_selected_tools,
      incoming.capability_selected_tools,
    ),
    capability_planned_step_ids: mergeTraceStringLists(
      current.capability_planned_step_ids,
      incoming.capability_planned_step_ids,
    ),
    replan_request_id: current.replan_request_id || incoming.replan_request_id || null,
    replan_trigger: current.replan_trigger || incoming.replan_trigger || null,
    replan_triggers: mergeTraceStringLists(current.replan_triggers, incoming.replan_triggers),
    replan_signal_ids: mergeTraceStringLists(current.replan_signal_ids, incoming.replan_signal_ids),
    runtime_doctrine: current.runtime_doctrine || incoming.runtime_doctrine || null,
    runtime_stage: current.runtime_stage || incoming.runtime_stage || null,
    runtime_role: current.runtime_role || incoming.runtime_role || null,
    requires_observation: current.requires_observation ?? incoming.requires_observation ?? null,
    requires_post_action_verification: current.requires_post_action_verification ?? incoming.requires_post_action_verification ?? null,
    deferred_tool: current.deferred_tool || incoming.deferred_tool || null,
    deferred_input: {
      ...(incoming.deferred_input || {}),
      ...(current.deferred_input || {}),
    },
    deferred_context: {
      ...(incoming.deferred_context || {}),
      ...(current.deferred_context || {}),
    },
    deferred_continuation: mergeRecordLists(
      current.deferred_continuation,
      incoming.deferred_continuation,
    ),
    task_workspace_items: mergeRecordLists(current.task_workspace_items, incoming.task_workspace_items),
    task_verification_targets: mergeRecordLists(
      current.task_verification_targets,
      incoming.task_verification_targets,
    ),
    status: incoming.status || current.status,
    risk_level: current.risk_level || incoming.risk_level || null,
    policy_reason: current.policy_reason || incoming.policy_reason || null,
    input_preview: {
      ...(current.input_preview || {}),
      ...(incoming.input_preview || {}),
    },
    output_preview: Object.keys(outputPreview).length ? outputPreview : {},
    metadata: {
      ...(current.metadata || {}),
      ...(incoming.metadata || {}),
    },
    approval_id: current.approval_id || incoming.approval_id || null,
    started_at: current.started_at || incoming.started_at || '',
    completed_at: incoming.completed_at || (
      toolCallStatusIsTerminal(incoming.status) ? incoming.started_at || current.completed_at || null : current.completed_at || null
    ),
  };
}

function mergeArtifactTrace(
  current: Record<string, unknown>,
  incoming: Record<string, unknown>,
): Record<string, unknown> {
  const merged = { ...current };
  [
    'source_tool',
    'source_run_id',
    'source_runnable_id',
    'source_runnable_name',
    'workflow_id',
    'workflow_run_id',
    'workflow_node_id',
    'workflow_node_label',
    'workflow_step_label',
    'group_id',
    'group_run_id',
    ...TRACE_KEYS,
  ].forEach((key) => {
    if (!merged[key] && incoming[key]) merged[key] = incoming[key];
  });
  return merged;
}

function mergeArtifactTraceContext(
  artifactPayload: Record<string, unknown>,
  payload: Record<string, unknown>,
) {
  if (!artifactPayload.source_tool) artifactPayload.source_tool = payload.source_tool || payload.tool;
  if (!artifactPayload.source_runnable_id) {
    artifactPayload.source_runnable_id = payload.source_runnable_id
      || payload.source_agent_id
      || payload.member_agent_id
      || payload.agent_id;
  }
  if (!artifactPayload.source_runnable_name) {
    artifactPayload.source_runnable_name = payload.source_runnable_name
      || payload.source_agent_name
      || payload.member_agent_name
      || payload.agent_name;
  }
  [
    'workflow_id',
    'workflow_run_id',
    'workflow_node_id',
    'workflow_node_label',
    'group_id',
    'group_run_id',
    ...TRACE_KEYS,
  ].forEach((key) => {
    if (!artifactPayload[key] && payload[key]) artifactPayload[key] = payload[key];
  });
  if (!artifactPayload.group_run_id && payload.run_group_id) {
    artifactPayload.group_run_id = payload.run_group_id;
  }
}

function isApprovalRunEvent(eventType: string): boolean {
  return eventType.includes('approval_required')
    || eventType.includes('approval_approved')
    || eventType.includes('approval_rejected')
    || eventType.includes('approval_cancelled')
    || ['approval.required', 'approval.approved', 'approval.cancelled', 'approval.rejected', 'approval.timeout', 'tool.approved', 'tool.rejected'].includes(eventType);
}

function approvalStatusFromRunEvent(eventType: string): ApprovalCardSnapshot['status'] {
  if (eventType.includes('approval_approved') || eventType === 'approval.approved' || eventType === 'tool.approved') return 'approved';
  if (eventType.includes('approval_rejected') || eventType === 'approval.rejected' || eventType === 'tool.rejected') return 'rejected';
  if (eventType.includes('approval_cancelled') || eventType === 'approval.cancelled') return 'cancelled';
  if (eventType.includes('approval_timeout') || eventType === 'approval.timeout') return 'expired';
  return 'pending';
}

function approvalToolFromRunEvent(eventType: string): string {
  if (eventType.startsWith('workflow.')) return 'workflow.approval';
  if (eventType.startsWith('group.')) return 'group.approval';
  if (eventType.startsWith('agent.tool.') || eventType.startsWith('tool.') || eventType.startsWith('approval.')) return 'tool.approval';
  return '';
}

function isArtifactRunEvent(eventType: string): boolean {
  return [
    'artifact.created',
    'agent.artifact.write',
    'group.artifact.created',
    'group.shared_artifact.created',
    'workflow.node.artifact',
  ].includes(eventType);
}

function isToolRunEvent(eventType: string): boolean {
  if (runtimeEventIsDailyDesktopToolEvent(eventType)) return true;
  return [
    'agent.tool.call',
    'agent.tool.denied',
    TOOL_INPUT_RESOLUTION_EVENT_TYPE,
    'agent.tool.started',
    'agent.tool.failed',
    'agent.tool.skipped',
    'agent.tool.approval_required',
    'agent.tool.approval_approved',
    'agent.tool.approval_rejected',
    'agent.tool.approval_timeout',
    'agent.tool.approval_cancelled',
    'agent.tool.completed',
    'approval.cancelled',
    'approval.timeout',
    'tool.approved',
    'tool.approval_approved',
    'tool.approval_cancelled',
    'tool.approval_rejected',
    'tool.requested',
    'tool.started',
    'tool.approval_required',
    'tool.approval_timeout',
    'tool.denied',
    'tool.rejected',
    'tool.skipped',
    'tool.completed',
    'tool.failed',
    'tool.cancelled',
  ].includes(eventType);
}

function toolStatusFromRunEvent(eventType: string): string {
  if (eventType === 'tool.requested') return 'requested';
  if (eventType === TOOL_INPUT_RESOLUTION_EVENT_TYPE) return 'resolved';
  if (eventType === 'tool.started' || eventType === 'agent.tool.started') return 'running';
  if (eventType === 'tool.approval_required' || eventType === 'agent.tool.approval_required') return 'waiting_approval';
  if (eventType === 'agent.tool.approval_approved' || eventType === 'tool.approved' || eventType === 'tool.approval_approved') return 'approved';
  if (eventType === 'agent.tool.approval_rejected' || eventType === 'agent.tool.denied' || eventType === 'tool.rejected' || eventType === 'tool.denied' || eventType === 'tool.approval_rejected') return 'denied';
  if (eventType === 'agent.tool.approval_timeout' || eventType === 'approval.timeout' || eventType === 'tool.approval_timeout') return 'expired';
  if (eventType === 'agent.tool.approval_cancelled' || eventType === 'approval.cancelled' || eventType === 'tool.approval_cancelled') return 'cancelled';
  if (eventType === 'tool.failed' || eventType === 'agent.tool.failed') return 'failed';
  if (eventType === 'agent.tool.skipped' || eventType === 'tool.skipped') return 'skipped';
  if (eventType === 'tool.cancelled') return 'cancelled';
  return 'completed';
}

function toolStatusFromRunEventPayload(
  eventType: string,
  payload: Record<string, unknown>,
  outputPreview: Record<string, unknown>,
): string {
  if (runtimeEventIsDesktopIntent(eventType, 'approval_required')) return 'waiting_approval';
  if (runtimeEventIsDesktopPermissionRecovery(eventType)) return 'blocked';
  if (runtimeEventIsDesktopIntent(eventType, 'unavailable')) return 'blocked';
  if (runtimeEventIsDesktopIntent(eventType, 'completed')) {
    if (toolCallForegroundLockBusy(outputPreview) || outputPreview.foreground_lock_busy === true) return 'blocked';
    if (outputPreview.approval_required === true) return 'waiting_approval';
    if (outputPreview.ok === false) return 'failed';
    return 'completed';
  }
  const explicit = publicRunEventPayloadString(payload, 'status');
  if (explicit) return explicit;
  if (toolCallForegroundLockBusy(payload) || outputPreview.foreground_lock_busy === true) return 'blocked';
  return toolStatusFromRunEvent(eventType);
}

function dailyDesktopIntentOutputPreview(
  eventType: string,
  payload: Record<string, unknown>,
): Record<string, unknown> | undefined {
  const result = objectPreview(payload.result);
  if (result) return result;
  if (runtimeEventIsDesktopIntent(eventType, 'unavailable')) {
    return pickPresentRecord(payload, [
      'reason',
      'blocked_by',
      'blocked_summary',
      'recovery_actions',
      'allowed_tools',
    ]);
  }
  if (runtimeEventIsDesktopPermissionRecovery(eventType)) {
    return pickPresentRecord(payload, [
      'permission_targets',
      'affected_tools',
      'recovery_hints',
      'recovery_actions',
      'status',
    ]);
  }
  if (runtimeEventIsDesktopIntent(eventType, 'approval_required')) {
    return pickPresentRecord(payload, [
      'reason',
      'approval_id',
      'risk_level',
      'policy_reason',
    ]);
  }
  return undefined;
}

function toolCallOutputPreviewFromPayload(
  eventType: string,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const preview = dailyDesktopIntentOutputPreview(eventType, payload)
    || objectPreview(payload.output_preview)
    || objectPreview(payload.output)
    || objectPreview(payload.result)
    || {};
  const recoveryPreview = toolCallRecoveryOutputPreview(eventType, payload);
  const outputPreview = {
    ...recoveryPreview,
    ...preview,
  };
  if (payload.error !== undefined && outputPreview.error === undefined) {
    outputPreview.error = payload.error;
  }
  return outputPreview;
}

function toolCallRecoveryOutputPreview(
  eventType: string,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  if (
    eventType !== 'agent.tool.skipped'
    && eventType !== 'tool.skipped'
    && !runtimeEventIsDesktopIntent(eventType, 'unavailable')
    && !runtimeEventIsDesktopPermissionRecovery(eventType)
  ) {
    return {};
  }
  return pickPresentRecord(payload, [
    'reason',
    'hint',
    'skipped',
    'blocked_by',
    'blocked_summary',
    'blocked_by_app_resolution',
    'blocked_by_runtime_readiness',
    'blocked_by_user_goal',
    'blocking_condition',
    'blocking_conditions',
    'source_summary',
    'source_tool',
    'recommended_tools',
    'allowed_tools',
    'recovery_hints',
    'recovery_actions',
    'permission_targets',
    'missing_permissions',
    'affected_tools',
  ]) || {};
}

function pickPresentRecord(source: Record<string, unknown>, keys: string[]): Record<string, unknown> | undefined {
  const result: Record<string, unknown> = {};
  keys.forEach((key) => {
    if (traceContextValuePresent(source[key])) result[key] = source[key];
  });
  return Object.keys(result).length ? result : undefined;
}

function toolCallForegroundLockBusy(payload: Record<string, unknown>): boolean {
  if (payload.foreground_lock_busy === true) return true;
  return ['output_preview', 'output', 'result'].some((key) => {
    const value = objectPreview(payload[key]);
    return value?.foreground_lock_busy === true;
  });
}

function toolCallStatusIsTerminal(status: string): boolean {
  return ['completed', 'failed', 'denied', 'skipped', 'expired', 'cancelled', 'blocked'].includes(status);
}

function toolCallCorrelationKey(event: PublicRunEvent, toolCall: ToolCallSnapshot): string {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const explicitId = publicRunEventPayloadString(payload, 'tool_call_id')
    || publicRunEventPayloadString(payload, 'id');
  if (explicitId) return `${event.run_id}:id:${explicitId}`;
  return [
    event.run_id,
    'tool',
    toolCall.tool_name,
    stableJson(toolCallCorrelationPreview(toolCall.input_preview || {})),
  ].join(':');
}

function latestMatchingToolCallIndex(
  calls: ToolCallSnapshot[],
  toolCall: ToolCallSnapshot,
): number | undefined {
  const key = toolCallSnapshotMatchKey(toolCall);
  for (let index = calls.length - 1; index >= 0; index -= 1) {
    if (toolCallSnapshotMatchKey(calls[index]) === key) return index;
  }
  return undefined;
}

function toolCallSnapshotMatchKey(toolCall: ToolCallSnapshot): string {
  return [
    toolCall.run_id || '',
    'tool',
    toolCall.tool_name,
    stableJson(toolCallCorrelationPreview(toolCall.input_preview || {})),
  ].join(':');
}

function toolCallCorrelationPreview(preview: Record<string, unknown>): Record<string, unknown> {
  const traceKeys = new Set([
    'agent_id',
    'agent_name',
    'approval_id',
    'app_resolution_source',
    'app_resolution_score',
    'app_resolution_confidence',
    'app_resolution_matched_capability',
    'app_resolution_matched_name',
    'app_resolution_matched_name_source',
    'app_resolution_reason',
    'group_id',
    'group_run_id',
    'member_agent_id',
    'member_agent_name',
    'policy_reason',
    'requested_app_name',
    'resolved_app_name',
    'resolved_app_path',
    'risk_level',
    'run_id',
    'run_group_id',
    'source_agent_id',
    'source_agent_name',
    'source_run_id',
    'source_runnable_id',
    'source_runnable_name',
    'task_verification_targets',
    'task_workspace_items',
    'source_tool',
    'tool_call_id',
    'verification_targets',
    'workflow_id',
    'workflow_node_id',
    'workflow_node_kind',
    'workflow_node_label',
    'workflow_run_id',
    'workflow_step_label',
    'workspace_items',
    ...TRACE_KEYS,
  ]);
  return Object.fromEntries(
    Object.entries(preview).filter(([key]) => !traceKeys.has(key)),
  );
}

function toolInputResolutionPreview(
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
): Record<string, unknown> {
  const preview = { ...inputPreview };
  const resolvedAppName = publicRunEventPayloadString(payload, 'resolved_app_name');
  const requestedAppName = publicRunEventPayloadString(payload, 'requested_app_name');
  const sourceTool = publicRunEventPayloadString(payload, 'source_tool');
  const resolutionScore = publicRunEventPayloadString(payload, 'app_resolution_score');
  const resolutionConfidence = publicRunEventPayloadString(payload, 'app_resolution_confidence');
  const resolutionMatchedCapability = publicRunEventPayloadString(payload, 'app_resolution_matched_capability');
  const resolutionMatchedName = publicRunEventPayloadString(payload, 'app_resolution_matched_name');
  const resolutionMatchedNameSource = publicRunEventPayloadString(payload, 'app_resolution_matched_name_source');
  const resolutionReason = publicRunEventPayloadString(payload, 'app_resolution_reason');
  const resolvedAppPath = publicRunEventPayloadString(payload, 'resolved_app_path');
  if (resolvedAppName) {
    if (!preview.app_name) preview.app_name = resolvedAppName;
    if (!preview.resolved_app_name) preview.resolved_app_name = resolvedAppName;
  }
  if (requestedAppName && !preview.requested_app_name) {
    preview.requested_app_name = requestedAppName;
  }
  if (sourceTool && !preview.app_resolution_source) {
    preview.app_resolution_source = sourceTool;
  }
  if (resolutionScore && !preview.app_resolution_score) {
    preview.app_resolution_score = resolutionScore;
  }
  if (resolutionConfidence && !preview.app_resolution_confidence) {
    preview.app_resolution_confidence = resolutionConfidence;
  }
  if (resolutionMatchedCapability && !preview.app_resolution_matched_capability) {
    preview.app_resolution_matched_capability = resolutionMatchedCapability;
  }
  if (resolutionMatchedName && !preview.app_resolution_matched_name) {
    preview.app_resolution_matched_name = resolutionMatchedName;
  }
  if (resolutionMatchedNameSource && !preview.app_resolution_matched_name_source) {
    preview.app_resolution_matched_name_source = resolutionMatchedNameSource;
  }
  if (resolutionReason && !preview.app_resolution_reason) {
    preview.app_resolution_reason = resolutionReason;
  }
  if (resolvedAppPath && !preview.resolved_app_path) {
    preview.resolved_app_path = resolvedAppPath;
  }
  return preview;
}

function toolCallMetadata(payload: Record<string, unknown>): Record<string, unknown> {
  const metadata = { ...(objectPreview(payload.metadata) || {}) };
  ['followup_target', 'action_target', 'observation_evidence', 'observation_retry'].forEach((key) => {
    const value = objectPreview(payload[key]);
    if (value) metadata[key] = value;
  });
  return metadata;
}

function approvalTaskWorkspaceItems(
  source: Record<string, unknown>,
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
): Array<Record<string, unknown>> {
  return mergeRecordLists(
    recordList(source.task_workspace_items),
    recordList(payload.task_workspace_items),
    recordList(inputPreview.task_workspace_items),
    recordList(source.workspace_items),
    recordList(payload.workspace_items),
    recordList(inputPreview.workspace_items),
  );
}

function approvalTaskVerificationTargets(
  source: Record<string, unknown>,
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
): Array<Record<string, unknown>> {
  return mergeRecordLists(
    recordList(source.task_verification_targets),
    recordList(payload.task_verification_targets),
    recordList(inputPreview.task_verification_targets),
    recordList(source.verification_targets),
    recordList(payload.verification_targets),
    recordList(inputPreview.verification_targets),
  );
}

function toolCallTaskWorkspaceItems(
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
): Array<Record<string, unknown>> {
  return mergeRecordLists(
    recordList(payload.task_workspace_items),
    recordList(inputPreview.task_workspace_items),
    recordList(payload.workspace_items),
    recordList(inputPreview.workspace_items),
  );
}

function toolCallTaskVerificationTargets(
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
): Array<Record<string, unknown>> {
  return mergeRecordLists(
    recordList(payload.task_verification_targets),
    recordList(inputPreview.task_verification_targets),
    recordList(payload.verification_targets),
    recordList(inputPreview.verification_targets),
  );
}

function toolCallInputPreviewWithTraceContext(
  inputPreview: Record<string, unknown>,
  traceContext: Record<string, unknown>,
): Record<string, unknown> {
  const preview = { ...inputPreview };
  Object.entries(traceContext).forEach(([key, value]) => {
    if (!preview[key] && traceContextValuePresent(value)) preview[key] = value;
  });
  return preview;
}

function traceContextValuePresent(value: unknown): boolean {
  if (typeof value === 'string') return Boolean(value.trim());
  if (Array.isArray(value)) return value.length > 0;
  return value !== undefined && value !== null && value !== false;
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => (
    Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  ));
}

function mergeRecordLists(
  ...lists: Array<Array<Record<string, unknown>> | undefined>
): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  const records: Array<Record<string, unknown>> = [];
  lists.flatMap((list) => list || []).forEach((record) => {
    const key = stableJson(record);
    if (seen.has(key)) return;
    seen.add(key);
    records.push(record);
  });
  return records;
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(stableJsonValue(value));
  } catch {
    return String(value);
  }
}

function stableJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableJsonValue);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, stableJsonValue(item)]),
  );
}

function artifactRecordKey(artifact: Record<string, unknown>, index: number): string {
  return publicRunEventPayloadString(artifact, 'artifact_id')
    || [
      publicRunEventPayloadString(artifact, 'source_run_id') || publicRunEventPayloadString(artifact, 'run_id'),
      publicRunEventPayloadString(artifact, 'path') || publicRunEventPayloadString(artifact, 'artifact_path'),
      publicRunEventPayloadString(artifact, 'title'),
      publicRunEventPayloadString(artifact, 'kind'),
    ].filter(Boolean).join(':')
    || `artifact:${index}`;
}

function approvalRecordKey(approval: ApprovalCardSnapshot, index: number): string {
  return approval.approval_id
    || [approval.run_id || '', approval.tool_name || '', approval.title || ''].filter(Boolean).join(':')
    || `approval:${index}`;
}

function approvalReplayCorrelationKeys(approval: ApprovalCardSnapshot): ApprovalReplayCorrelationKeys {
  const preview = approvalReplayCorrelationPreview(approval.input_preview || {});
  const baseParts = [
    approval.run_id || '',
    'approval',
    approval.tool_name || '',
    approval.workflow_node_id || '',
    approval.group_run_id || '',
    approval.source_runnable_id || '',
  ];
  const strongKeys = [
    [...baseParts, stableJson(preview)].join(':'),
    approval.approval_id ? `${approval.run_id || ''}:approval_id:${approval.approval_id}` : '',
  ].filter(Boolean);
  const weakKey = baseParts.slice(2).some(Boolean) ? baseParts.join(':') : '';
  return { strongKeys: Array.from(new Set(strongKeys)), weakKey };
}

function approvalReplayActiveIndex(
  keys: ApprovalReplayCorrelationKeys,
  activeByStrongKey: Map<string, number>,
  activeByWeakKey: Map<string, ApprovalReplayWeakIndex>,
  allowWeak: boolean,
): number | undefined {
  for (const key of keys.strongKeys) {
    const index = activeByStrongKey.get(key);
    if (index !== undefined) return index;
  }
  if (!allowWeak) return undefined;
  const weakIndex = keys.weakKey ? activeByWeakKey.get(keys.weakKey) : undefined;
  return typeof weakIndex === 'number' ? weakIndex : undefined;
}

function registerActiveApprovalReplay(
  index: number,
  keys: ApprovalReplayCorrelationKeys,
  activeByStrongKey: Map<string, number>,
  activeByWeakKey: Map<string, ApprovalReplayWeakIndex>,
  activeKeysByIndex: Map<number, ApprovalReplayCorrelationKeys>,
) {
  keys.strongKeys.forEach((key) => activeByStrongKey.set(key, index));
  if (keys.weakKey) {
    const existing = activeByWeakKey.get(keys.weakKey);
    if (existing === undefined) {
      activeByWeakKey.set(keys.weakKey, index);
    } else if (existing !== index) {
      activeByWeakKey.set(keys.weakKey, 'ambiguous');
    }
  }
  activeKeysByIndex.set(index, keys);
}

function unregisterActiveApprovalReplay(
  index: number,
  activeByStrongKey: Map<string, number>,
  activeByWeakKey: Map<string, ApprovalReplayWeakIndex>,
  activeKeysByIndex: Map<number, ApprovalReplayCorrelationKeys>,
) {
  const keys = activeKeysByIndex.get(index);
  if (!keys) return;
  keys.strongKeys.forEach((key) => {
    if (activeByStrongKey.get(key) === index) activeByStrongKey.delete(key);
  });
  if (keys.weakKey && activeByWeakKey.get(keys.weakKey) === index) {
    activeByWeakKey.delete(keys.weakKey);
  }
  activeKeysByIndex.delete(index);
}

function approvalReplayCorrelationPreview(preview: Record<string, unknown>): Record<string, unknown> {
  const traceKeys = new Set([
    'agent_id',
    'agent_name',
    'approval_id',
    'group_id',
    'group_run_id',
    'member_agent_id',
    'member_agent_name',
    'policy_reason',
    'risk_level',
    'run_id',
    'run_group_id',
    'source_agent_id',
    'source_agent_name',
    'source_run_id',
    'source_runnable_id',
    'source_runnable_name',
    'source_tool',
    'tool_call_id',
    'workflow_id',
    'workflow_node_id',
    'workflow_node_kind',
    'workflow_node_label',
    'workflow_run_id',
    'workflow_step_label',
    ...TRACE_KEYS,
  ]);
  return Object.fromEntries(
    Object.entries(preview).filter(([key]) => !traceKeys.has(key)),
  );
}

function plannerTraceString(
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
  key: string,
): string | null {
  return publicRunEventPayloadString(payload, key)
    || publicRunEventPayloadString(inputPreview, key)
    || null;
}

function plannerTraceStringList(
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
  key: string,
): string[] {
  return mergeTraceStringLists(
    publicRunEventPayloadStringList(payload, key),
    publicRunEventPayloadStringList(inputPreview, key),
  );
}

function plannerTraceBool(
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
  key: string,
): boolean | null {
  return publicRunEventPayloadBool(payload, key) ?? publicRunEventPayloadBool(inputPreview, key);
}

function eventTraceString(
  source: Record<string, unknown>,
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
  key: string,
): string | null {
  return publicRunEventPayloadString(source, key)
    || publicRunEventPayloadString(payload, key)
    || publicRunEventPayloadString(inputPreview, key)
    || null;
}

function eventTraceStringList(
  source: Record<string, unknown>,
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
  key: string,
): string[] {
  return mergeTraceStringLists(
    publicRunEventPayloadStringList(source, key),
    publicRunEventPayloadStringList(payload, key),
    publicRunEventPayloadStringList(inputPreview, key),
  );
}

function eventTraceBool(
  source: Record<string, unknown>,
  payload: Record<string, unknown>,
  inputPreview: Record<string, unknown>,
  key: string,
): boolean | null {
  return publicRunEventPayloadBool(source, key)
    ?? publicRunEventPayloadBool(payload, key)
    ?? publicRunEventPayloadBool(inputPreview, key);
}

function publicRunEventPayloadStringList(
  payload: Record<string, unknown>,
  key: string,
): string[] {
  const value = payload[key];
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean);
  }
  const single = publicRunEventPayloadString(payload, key);
  return single ? [single] : [];
}

function publicRunEventPayloadBool(
  payload: Record<string, unknown>,
  key: string,
): boolean | null {
  const value = payload[key];
  if (value === true || value === false) return value;
  const clean = publicRunEventPayloadString(payload, key).toLowerCase();
  if (clean === 'true' || clean === 'required') return true;
  if (clean === 'false') return false;
  return null;
}

function mergeTraceStringLists(...lists: Array<string[] | null | undefined>): string[] {
  const values: string[] = [];
  lists.flatMap((list) => list || []).forEach((value) => {
    const clean = String(value || '').trim();
    if (clean && !values.includes(clean)) values.push(clean);
  });
  return values;
}

function objectPreview(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function publicRunEventPayloadWithContext(event: PublicRunEvent): Record<string, unknown> {
  return {
    ...(objectPreview(event.payload) || {}),
    ...publicRunEventContextRecord(event),
  };
}

function publicRunEventContextRecord(event: PublicRunEvent): Record<string, unknown> {
  const context: Record<string, unknown> = {};
  setPublicRunEventContextValue(context, 'parent_run_id', event.parent_run_id);
  setPublicRunEventContextValue(context, 'source_run_id', event.source_run_id);
  setPublicRunEventContextValue(context, 'core_id', event.core_id);
  setPublicRunEventContextValue(context, 'workspace_id', event.workspace_id);
  setPublicRunEventContextValue(context, 'task_id', event.task_id);
  setPublicRunEventContextValue(
    context,
    'source_runnable_id',
    publicRunEventContextString(event.source_runnable_id, event.member_agent_id, event.agent_id),
  );
  setPublicRunEventContextValue(
    context,
    'source_runnable_name',
    publicRunEventContextString(event.source_runnable_name, event.member_agent_name, event.agent_name),
  );
  setPublicRunEventContextValue(context, 'workflow_id', event.workflow_id);
  setPublicRunEventContextValue(context, 'workflow_run_id', event.workflow_run_id);
  setPublicRunEventContextValue(context, 'workflow_node_id', event.workflow_node_id);
  setPublicRunEventContextValue(context, 'workflow_node_label', event.workflow_node_label);
  setPublicRunEventContextValue(context, 'group_id', event.group_id);
  setPublicRunEventContextValue(
    context,
    'group_run_id',
    publicRunEventContextString(event.group_run_id, event.run_group_id),
  );
  setPublicRunEventContextValue(
    context,
    'run_group_id',
    publicRunEventContextString(event.run_group_id, event.group_run_id),
  );
  setPublicRunEventContextValue(
    context,
    'agent_id',
    publicRunEventContextString(event.agent_id, event.member_agent_id),
  );
  setPublicRunEventContextValue(
    context,
    'agent_name',
    publicRunEventContextString(event.agent_name, event.member_agent_name),
  );
  setPublicRunEventContextValue(
    context,
    'member_agent_id',
    publicRunEventContextString(event.member_agent_id, event.agent_id),
  );
  setPublicRunEventContextValue(
    context,
    'member_agent_name',
    publicRunEventContextString(event.member_agent_name, event.agent_name),
  );
  return context;
}

function setPublicRunEventContextValue(
  context: Record<string, unknown>,
  key: string,
  value: unknown,
) {
  const text = publicRunEventContextString(value);
  if (text) context[key] = text;
}

function publicRunEventContextString(...values: unknown[]): string {
  for (const value of values) {
    const text = typeof value === 'string' ? value.trim() : '';
    if (text) return text;
  }
  return '';
}

function publicRunEventPayloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value.trim() : '';
}
